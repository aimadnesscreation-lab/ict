"""
Tests for API endpoint data freshness after exchange position sync.

Verifies that /trades, /performance, /demo/account, and /api/diagnostics
return up-to-date DemoAccount state *immediately* after sync_positions()
closes positions — without needing a candle close event to refresh
stale caches.

This tests the fix that replaced stale _recent_trades and _performance_cache
reads with direct _demo_account reads in api/main.py.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from demo_account import DemoAccount, OpenPosition, ClosedTrade
from execution.executor import LiveExecutor
from execution.sync_worker import sync_positions
from api import main as api_main


# ── Helpers ──────────────────────────────────────────────────────────

def make_mock_executor(open_positions: list | None = None) -> AsyncMock:
    """Create a mocked LiveExecutor with controlled get_open_positions()."""
    executor = AsyncMock(spec=LiveExecutor)
    executor.exchange = MagicMock()
    executor.get_open_positions = AsyncMock(return_value=open_positions or [])
    return executor


def demo_with_state() -> tuple[DemoAccount, datetime]:
    """Create a DemoAccount with one pre-existing closed trade.

    The pre-existing trade uses an exit_time *before* the returned `now`
    so that any trade closed by sync (which uses `now`) always sorts
    as the newest in reverse-chronological order.
    """
    demo = DemoAccount(initial_balance=5000.0)
    now = datetime(2026, 6, 23, 12, 0, 0, tzinfo=timezone.utc)
    earlier = datetime(2026, 6, 23, 11, 59, 59, tzinfo=timezone.utc)  # 1s before now

    # Pre-existing closed trade — WIN from a previous TP hit
    demo.closed_trades.append(ClosedTrade(
        symbol="ETHUSDT",
        signal_type="BUY",
        side="LONG",
        entry_time=earlier,
        exit_time=earlier,
        entry_price=1650.0,
        exit_price=1670.0,
        stop_loss=1625.0,
        take_profit=1700.0,
        quantity=0.5,
        profit=10.0,
        profit_pct=0.0061,
        rr=1.0,
        result="WIN",
        exit_reason="TAKE_PROFIT",
    ))
    demo.balance = 5010.0  # initial 5000 + 10 profit
    demo._peak_balance = 5010.0
    return demo, now


def add_open_position(demo: DemoAccount, now: datetime) -> None:
    """Add an open LONG position to the demo account."""
    demo.open_positions["ETHUSDT"] = OpenPosition(
        symbol="ETHUSDT",
        signal_type="BUY",
        side="LONG",
        entry_time=now,
        entry_price=1660.0,
        stop_loss=1625.0,
        take_profit=1730.0,
        quantity=1.0,
        risk_amount=35.0,
        atr=17.5,
    )


# ── Tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trades_reflects_synced_sl_close():
    """
    After sync_positions() closes a LONG position as SL hit,
    /trades should immediately include the newly closed trade
    with correct exit_reason and negative P&L.
    """
    demo, now = demo_with_state()
    add_open_position(demo, now)

    # Simulate sync: exchange no longer has the position, price below SL
    executor = make_mock_executor([])
    prices = {"ETHUSDT": 1620.0}
    result = await sync_positions(demo, executor, latest_prices=prices, current_time=now)
    assert result.positions_closed_from_exchange_sl == 1

    # Hit /trades endpoint — should see 2 trades (pre-existing + synced)
    with patch.object(api_main, "_demo_account", demo), \
         patch.object(api_main, "_latest_prices", prices):
        client = TestClient(api_main.app)
        resp = client.get("/trades?limit=50")

    assert resp.status_code == 200
    trades = resp.json()
    assert len(trades) >= 2, f"Expected >=2 trades, got {len(trades)}"

    # The newest trade (first in list, reverse chronological by exit_time)
    # Should be the sync-closed LOSS trade (exit_time=now), not the pre-existing WIN
    newest = trades[0]
    assert newest["symbol"] == "ETHUSDT"
    assert newest["result"] == "LOSS"
    assert newest["exit_reason"] == "SYNC_STOP_LOSS"
    assert isinstance(newest["profit"], (int, float))
    assert newest["profit"] < 0


@pytest.mark.asyncio
async def test_trades_reflects_synced_tp_close():
    """
    After sync_positions() closes a LONG position as TP hit,
    /trades should include the trade with positive P&L.
    """
    demo, now = demo_with_state()
    add_open_position(demo, now)

    # Simulate sync: exchange no longer has the position, price above TP
    executor = make_mock_executor([])
    prices = {"ETHUSDT": 1740.0}
    result = await sync_positions(demo, executor, latest_prices=prices, current_time=now)
    assert result.positions_closed_from_exchange_tp == 1

    with patch.object(api_main, "_demo_account", demo), \
         patch.object(api_main, "_latest_prices", prices):
        client = TestClient(api_main.app)
        resp = client.get("/trades?limit=50")

    assert resp.status_code == 200
    trades = resp.json()
    # Newest trade should be the sync-closed WIN (exit_time=now)
    newest = trades[0]
    assert newest["symbol"] == "ETHUSDT"
    assert newest["result"] == "WIN"
    assert newest["exit_reason"] == "SYNC_TAKE_PROFIT"
    assert isinstance(newest["profit"], (int, float))
    assert newest["profit"] > 0


@pytest.mark.asyncio
async def test_performance_updates_after_sync_sl():
    """
    After sync closes a position via SL, /performance should reflect
    the updated total_trades and decreased total P&L.
    """
    demo, now = demo_with_state()
    add_open_position(demo, now)

    # Capture pre-sync performance
    pre_perf = demo.get_performance()
    assert pre_perf["total_trades"] == 1  # only the pre-existing trade

    # Sync closes the open position (SL hit)
    executor = make_mock_executor([])
    prices = {"ETHUSDT": 1620.0}
    await sync_positions(demo, executor, latest_prices=prices, current_time=now)

    # Verify performance reflects the new trade
    post_perf = demo.get_performance()
    assert post_perf["total_trades"] == 2
    assert post_perf["total_profit"] < pre_perf["total_profit"]

    # Hit /performance endpoint — should match post_perf
    with patch.object(api_main, "_demo_account", demo), \
         patch.object(api_main, "_latest_prices", prices):
        client = TestClient(api_main.app)
        resp = client.get("/performance")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_trades"] == 2
    assert isinstance(data["total_pnl"], (int, float))
    assert data["total_pnl"] < 10.0  # original profit of $10 reduced by SL loss


@pytest.mark.asyncio
async def test_demo_account_endpoint_fresh_after_sync():
    """
    After sync closes a position, /demo/account should show the correct
    updated balance and zero open positions.
    """
    demo, now = demo_with_state()
    add_open_position(demo, now)
    assert len(demo.open_positions) == 1
    assert demo.balance == 5010.0

    # Sync closes the position (SL hit)
    executor = make_mock_executor([])
    prices = {"ETHUSDT": 1620.0}
    await sync_positions(demo, executor, latest_prices=prices, current_time=now)

    # Position should be closed, balance decreased
    assert len(demo.open_positions) == 0
    assert demo.balance < 5010.0

    with patch.object(api_main, "_demo_account", demo), \
         patch.object(api_main, "_latest_prices", prices):
        client = TestClient(api_main.app)
        resp = client.get("/demo/account")

    assert resp.status_code == 200
    acct = resp.json()
    assert acct["open_positions_count"] == 0
    assert acct["open_positions"] == []
    assert isinstance(acct["balance"], (int, float))
    assert acct["balance"] < 5010.0
    assert acct["total_trades"] == 2
    # The pre-existing WIN trade should still show in totals
    assert acct["total_profit"] < 10.0


@pytest.mark.asyncio
async def test_diagnostics_trade_count_fresh_after_sync():
    """
    After sync closes a position, /api/diagnostics should report the
    correct total_trades count from DemoAccount directly.
    """
    demo, now = demo_with_state()
    add_open_position(demo, now)
    assert len(demo.closed_trades) == 1  # pre-existing only

    executor = make_mock_executor([])
    prices = {"ETHUSDT": 1620.0}
    await sync_positions(demo, executor, latest_prices=prices, current_time=now)
    assert len(demo.closed_trades) == 2  # pre-existing + synced

    with patch.object(api_main, "_demo_account", demo), \
         patch.object(api_main, "_latest_prices", prices):
        client = TestClient(api_main.app)
        resp = client.get("/api/diagnostics")

    assert resp.status_code == 200
    diag = resp.json()
    assert diag["database"]["total_trades"] == 2
    assert diag["risk"]["daily_loss_pct"] > 0  # Loss incurred
    assert diag["risk"]["open_positions"] == 0


@pytest.mark.asyncio
async def test_all_endpoints_consistent_after_sync():
    """
    After a single sync event, all four data endpoints should return
    consistent state (same trade count, same balance direction).
    """
    demo, now = demo_with_state()
    add_open_position(demo, now)

    executor = make_mock_executor([])
    prices = {"ETHUSDT": 1620.0}
    await sync_positions(demo, executor, latest_prices=prices, current_time=now)

    with patch.object(api_main, "_demo_account", demo), \
         patch.object(api_main, "_latest_prices", prices):
        client = TestClient(api_main.app)

        # Hit all endpoints
        trades_resp = client.get("/trades?limit=50")
        perf_resp = client.get("/performance")
        acct_resp = client.get("/demo/account")
        diag_resp = client.get("/api/diagnostics")

    # All should return 200
    assert trades_resp.status_code == 200
    assert perf_resp.status_code == 200
    assert acct_resp.status_code == 200
    assert diag_resp.status_code == 200

    trades_data = trades_resp.json()
    perf_data = perf_resp.json()
    acct_data = acct_resp.json()
    diag_data = diag_resp.json()

    # Trade count consistent across endpoints
    assert len(trades_data) >= 2
    assert perf_data["total_trades"] == 2
    assert acct_data["total_trades"] == 2
    assert diag_data["database"]["total_trades"] == 2

    # Latest trade (newest exit_time) is a LOSS from SL hit
    assert trades_data[0]["result"] == "LOSS"
    assert trades_data[0]["exit_reason"] == "SYNC_STOP_LOSS"

    # P&L decreased after the loss (was $10.00, now less)
    assert perf_data["total_pnl"] < 10.0
    assert acct_data["total_profit"] < 10.0
    assert acct_data["open_positions_count"] == 0


@pytest.mark.asyncio
async def test_multiple_sync_cycles_preserve_freshness():
    """
    After multiple sync cycles, endpoints should always reflect the
    latest state — not a snapshot from the first cycle.
    """
    demo, now = demo_with_state()
    add_open_position(demo, now)
    executor = make_mock_executor([])
    prices = {"ETHUSDT": 1620.0}

    # Cycle 1: Close position via SL
    result1 = await sync_positions(demo, executor, latest_prices=prices, current_time=now)
    assert result1.positions_closed_from_exchange_sl == 1
    balance_after_sl = demo.balance

    with patch.object(api_main, "_demo_account", demo), \
         patch.object(api_main, "_latest_prices", prices):
        client = TestClient(api_main.app)
        resp1 = client.get("/demo/account")
        assert resp1.status_code == 200
        assert resp1.json()["open_positions_count"] == 0
        assert resp1.json()["balance"] == balance_after_sl
        assert resp1.json()["total_trades"] == 2

    # Cycle 2: No positions to sync — state should remain unchanged
    result2 = await sync_positions(demo, executor, latest_prices=prices, current_time=now)
    assert result2.demo_positions_checked == 0
    assert demo.balance == balance_after_sl  # Unchanged

    with patch.object(api_main, "_demo_account", demo), \
         patch.object(api_main, "_latest_prices", prices):
        client = TestClient(api_main.app)

        # All endpoints should still show the same state
        resp2a = client.get("/trades?limit=50")
        resp2b = client.get("/performance")
        resp2c = client.get("/demo/account")
        resp2d = client.get("/api/diagnostics")

    assert resp2a.status_code == 200
    assert resp2b.status_code == 200
    assert resp2c.status_code == 200
    assert resp2d.status_code == 200

    data = resp2c.json()
    assert data["open_positions_count"] == 0
    assert data["balance"] == balance_after_sl
    assert data["total_trades"] == 2
    assert resp2b.json()["total_trades"] == 2
    assert resp2d.json()["database"]["total_trades"] == 2


@pytest.mark.asyncio
async def test_endpoints_dont_use_stale_caches():
    """
    Verification that the endpoints read from DemoAccount directly
    (not from _recent_trades or _performance_cache) by proving that
    even after a sync event modifies DemoAccount, the endpoints
    return the updated state.
    """
    demo, now = demo_with_state()
    add_open_position(demo, now)

    # Sync closes the position
    executor = make_mock_executor([])
    prices = {"ETHUSDT": 1620.0}
    await sync_positions(demo, executor, latest_prices=prices, current_time=now)

    # The old _recent_trades and _performance_cache are gone,
    # but verify endpoints work without them
    assert not hasattr(api_main, "_recent_trades"), \
        "Stale _recent_trades cache should have been removed"
    assert not hasattr(api_main, "_performance_cache"), \
        "Stale _performance_cache should have been removed"

    # Endpoints should still work fine
    with patch.object(api_main, "_demo_account", demo), \
         patch.object(api_main, "_latest_prices", prices):
        client = TestClient(api_main.app)
        assert client.get("/trades?limit=50").status_code == 200
        assert client.get("/performance").status_code == 200
        assert client.get("/demo/account").status_code == 200
        assert client.get("/api/diagnostics").status_code == 200
