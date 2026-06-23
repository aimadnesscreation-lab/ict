"""
Tests for Exchange Position Sync Worker — sync_positions().

Covers the reconciliation logic between DemoAccount and the live Binance exchange:
  - No positions to sync (no-op)
  - SL hit on exchange → close in DemoAccount
  - TP hit on exchange → close in DemoAccount
  - Manual close on exchange → close in DemoAccount
  - Partial fill (exchange qty < DemoAccount qty)
  - Side mismatch (Demo LONG, Exchange SHORT)
  - Missing exchange (no connection)
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List

from demo_account import DemoAccount, OpenPosition
from execution.executor import LiveExecutor
from execution.sync_worker import sync_positions, SyncResult


# ── Helpers ──────────────────────────────────────────────────────────

def make_mock_executor(open_positions: List[Dict] | None = None) -> AsyncMock:
    """Create a mocked LiveExecutor with controlled get_open_positions()."""
    executor = AsyncMock(spec=LiveExecutor)
    executor.exchange = MagicMock()  # Non-None to bypass the no-exchange guard
    executor.get_open_positions = AsyncMock(return_value=open_positions or [])
    return executor


def add_demo_position(
    demo: DemoAccount,
    symbol: str = "ETHUSDT",
    side: str = "LONG",
    entry: float = 1660.0,
    sl: float = 1625.0,
    tp: float = 1730.0,
    qty: float = 1.0,
    now: datetime | None = None,
) -> OpenPosition:
    """Manually add an OpenPosition to DemoAccount for testing."""
    pos = OpenPosition(
        symbol=symbol,
        signal_type="BUY" if side == "LONG" else "SELL",
        side=side,
        entry_time=now or datetime.now(timezone.utc),
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        quantity=qty,
        risk_amount=abs(entry - sl) * qty,
        atr=abs(entry - sl) / 2.0,
    )
    demo.open_positions[symbol] = pos
    return pos


def make_exchange_pos(
    symbol: str = "ETH/USDT:USDT",
    side: str = "long",  # CCXT returns 'long' or 'short'
    contracts: float = 1.0,
    entry: float = 1660.0,
) -> Dict:
    """Create a mock exchange position dict matching CCXT format."""
    return {
        "symbol": symbol,
        "side": side,
        "contracts": contracts,
        "size": contracts,
        "entryPrice": entry,
        "unrealizedPnl": 0.0,
        "leverage": 3.0,
        "liquidationPrice": 0.0,
        "initialMargin": 100.0,
        "percentage": 0.0,
    }


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_no_positions():
    """Empty sync: no DemoAccount positions, no exchange positions → no-op."""
    demo = DemoAccount(initial_balance=5000.0)
    executor = make_mock_executor([])

    result = await sync_positions(demo, executor, latest_prices={})

    assert result.demo_positions_checked == 0
    assert result.exchange_positions_checked == 0
    assert result.positions_closed_from_exchange_sl == 0
    assert result.positions_closed_from_exchange_tp == 0
    assert result.positions_closed_from_exchange_manual == 0
    assert len(result.discrepancies) == 0
    assert len(result.errors) == 0
    assert demo.balance == 5000.0
    assert len(demo.open_positions) == 0


@pytest.mark.asyncio
async def test_sync_no_exchange():
    """No exchange connection → result has error, nothing happens."""
    demo = DemoAccount(initial_balance=5000.0)
    executor = MagicMock(spec=LiveExecutor)
    executor.exchange = None

    result = await sync_positions(demo, executor, latest_prices={})

    assert len(result.errors) == 1
    assert "No exchange connection" in result.errors[0]


@pytest.mark.asyncio
async def test_sync_sl_hit_long():
    """
    LONG position: exchange no longer has the position, current price is
    at/below SL → DemoAccount closes it as STOP_LOSS.
    """
    now = datetime.now(timezone.utc)
    demo = DemoAccount(initial_balance=5000.0)
    add_demo_position(demo, side="LONG", entry=1660.0, sl=1625.0, tp=1730.0, now=now)
    executor = make_mock_executor([])  # No positions on exchange
    prices = {"ETHUSDT": 1620.0}  # Price below SL

    result = await sync_positions(demo, executor, latest_prices=prices, current_time=now)

    assert result.demo_positions_checked == 1
    assert result.exchange_positions_checked == 0
    assert result.positions_closed_from_exchange_sl == 1
    assert "ETHUSDT" not in demo.open_positions
    assert len(demo.closed_trades) == 1
    trade = demo.closed_trades[0]
    assert trade.result == "LOSS"
    assert trade.exit_reason == "SYNC_STOP_LOSS"
    assert trade.exit_price == 1625.0  # SL price
    assert trade.profit < 0
    # Balance decreased by the loss amount
    assert demo.balance < 5000.0


@pytest.mark.asyncio
async def test_sync_tp_hit_long():
    """
    LONG position: exchange no longer has the position, current price is
    at/above TP → DemoAccount closes it as TAKE_PROFIT.
    """
    now = datetime.now(timezone.utc)
    demo = DemoAccount(initial_balance=5000.0)
    add_demo_position(demo, side="LONG", entry=1660.0, sl=1625.0, tp=1730.0, now=now)
    executor = make_mock_executor([])
    prices = {"ETHUSDT": 1740.0}  # Price above TP

    result = await sync_positions(demo, executor, latest_prices=prices, current_time=now)

    assert result.positions_closed_from_exchange_tp == 1
    assert "ETHUSDT" not in demo.open_positions
    trade = demo.closed_trades[0]
    assert trade.result == "WIN"
    assert trade.exit_reason == "SYNC_TAKE_PROFIT"
    assert trade.exit_price == 1730.0  # TP price
    assert trade.profit > 0
    assert demo.balance > 5000.0


@pytest.mark.asyncio
async def test_sync_manual_close_long():
    """
    LONG position: exchange no longer has the position, current price is
    between SL and TP → DemoAccount closes it as MANUAL.
    """
    now = datetime.now(timezone.utc)
    demo = DemoAccount(initial_balance=5000.0)
    add_demo_position(demo, side="LONG", entry=1660.0, sl=1625.0, tp=1730.0, now=now)
    executor = make_mock_executor([])
    prices = {"ETHUSDT": 1680.0}  # Price between SL and TP

    result = await sync_positions(demo, executor, latest_prices=prices, current_time=now)

    assert result.positions_closed_from_exchange_manual == 1
    assert "ETHUSDT" not in demo.open_positions
    trade = demo.closed_trades[0]
    assert trade.exit_reason == "SYNC_MANUAL"
    assert trade.exit_price == 1680.0  # Current price used


@pytest.mark.asyncio
async def test_sync_sl_hit_short():
    """
    SHORT position: exchange no longer has the position, current price is
    at/above SL → DemoAccount closes it as STOP_LOSS.
    """
    now = datetime.now(timezone.utc)
    demo = DemoAccount(initial_balance=5000.0)
    add_demo_position(demo, side="SHORT", entry=1660.0, sl=1695.0, tp=1590.0, now=now)
    executor = make_mock_executor([])
    prices = {"ETHUSDT": 1700.0}  # Price above SL

    result = await sync_positions(demo, executor, latest_prices=prices, current_time=now)

    assert result.positions_closed_from_exchange_sl == 1
    assert "ETHUSDT" not in demo.open_positions
    trade = demo.closed_trades[0]
    assert trade.result == "LOSS"
    assert trade.exit_reason == "SYNC_STOP_LOSS"
    assert trade.exit_price == 1695.0


@pytest.mark.asyncio
async def test_sync_partial_fill_long():
    """
    LONG position: exchange has a smaller qty than DemoAccount (partial close).
    DemoAccount should reduce the position size and record a partial fill trade.
    """
    now = datetime.now(timezone.utc)
    demo = DemoAccount(initial_balance=5000.0)
    add_demo_position(demo, side="LONG", entry=1660.0, sl=1625.0, tp=1730.0, qty=2.0, now=now)
    # Exchange only has 1.0 contracts (50% of demo position)
    exchange_pos = make_exchange_pos(contracts=1.0, entry=1660.0)
    executor = make_mock_executor([exchange_pos])
    prices = {"ETHUSDT": 1665.0}

    result = await sync_positions(demo, executor, latest_prices=prices, current_time=now)

    # Should have closed ~1.0 as partial fill (50% of 2.0)
    assert result.positions_closed_from_exchange_manual == 1
    assert "ETHUSDT" in demo.open_positions  # Position still open, but reduced
    assert demo.open_positions["ETHUSDT"].quantity == pytest.approx(1.0, rel=0.01)
    assert len(demo.closed_trades) == 1
    trade = demo.closed_trades[0]
    assert "PARTIAL" in trade.exit_reason
    assert trade.quantity == pytest.approx(1.0, rel=0.01)


@pytest.mark.asyncio
async def test_sync_partial_fill_small_diff_skipped():
    """
    Small qty mismatch (<5%) should be logged as a discrepancy but NOT
    trigger a partial close.
    """
    now = datetime.now(timezone.utc)
    demo = DemoAccount(initial_balance=5000.0)
    add_demo_position(demo, side="LONG", entry=1660.0, sl=1625.0, tp=1730.0, qty=1.0, now=now)
    # Exchange has 0.98 contracts (2% difference — safe from float precision issues)
    exchange_pos = make_exchange_pos(contracts=0.98, entry=1660.0)
    executor = make_mock_executor([exchange_pos])
    prices = {"ETHUSDT": 1665.0}

    result = await sync_positions(demo, executor, latest_prices=prices, current_time=now)

    # No trade closed for small differences
    assert result.positions_closed_from_exchange_manual == 0
    assert len(demo.closed_trades) == 0
    # But should have a discrepancy logged
    assert len(result.discrepancies) >= 1


@pytest.mark.asyncio
async def test_sync_multi_symbol():
    """Multiple symbols: each is reconciled independently."""
    now = datetime.now(timezone.utc)
    demo = DemoAccount(initial_balance=10000.0)
    add_demo_position(demo, symbol="ETHUSDT", side="LONG", entry=1660.0, sl=1625.0, tp=1730.0, now=now)
    add_demo_position(demo, symbol="BTCUSDT", side="LONG", entry=67000.0, sl=65000.0, tp=70000.0, now=now)

    # Exchange still has ETH but NOT BTC (BTC hit SL)
    exchange_eth = make_exchange_pos(symbol="ETH/USDT:USDT", contracts=1.0)
    executor = make_mock_executor([exchange_eth])
    prices = {"ETHUSDT": 1665.0, "BTCUSDT": 64800.0}

    result = await sync_positions(demo, executor, latest_prices=prices, current_time=now)

    assert result.demo_positions_checked == 2
    assert result.exchange_positions_checked == 1
    # ETH still open (exists on exchange)
    assert "ETHUSDT" in demo.open_positions
    # BTC was closed (not on exchange, price below SL)
    assert "BTCUSDT" not in demo.open_positions
    assert result.positions_closed_from_exchange_sl >= 1


@pytest.mark.asyncio
async def test_sync_side_mismatch():
    """Side mismatch (Demo LONG, Exchange SHORT) logs discrepancy but doesn't close automatically."""
    now = datetime.now(timezone.utc)
    demo = DemoAccount(initial_balance=5000.0)
    add_demo_position(demo, side="LONG", entry=1660.0, sl=1625.0, tp=1730.0, now=now)
    # Exchange reports SHORT (negative contracts in CCXT convention)
    exchange_pos = make_exchange_pos(side="short", contracts=-1.0, entry=1660.0)
    executor = make_mock_executor([exchange_pos])
    prices = {"ETHUSDT": 1665.0}

    result = await sync_positions(demo, executor, latest_prices=prices, current_time=now)

    # Side mismatch is logged as discrepancy but doesn't auto-close
    assert len(result.discrepancies) >= 1
    # Position should still be open since exchange has it
    assert "ETHUSDT" in demo.open_positions


@pytest.mark.asyncio
async def test_sync_missing_price_closes_position():
    """
    If latest_prices doesn't have the symbol, current_price defaults to 0.
    For a LONG position, 0 < SL → position gets closed as STOP_LOSS.
    This is a known edge case: missing price data triggers an SL close.
    """
    now = datetime.now(timezone.utc)
    demo = DemoAccount(initial_balance=5000.0)
    add_demo_position(demo, side="LONG", entry=1660.0, sl=1625.0, tp=1730.0, now=now)
    executor = make_mock_executor([])
    prices = {}  # No price data for ETHUSDT

    result = await sync_positions(demo, executor, latest_prices=prices, current_time=now)

    # Position closed because default current_price=0 <= stop_loss
    assert "ETHUSDT" not in demo.open_positions
    assert result.positions_closed_from_exchange_sl == 1


@pytest.mark.asyncio
async def test_sync_multiple_cycles_balance_tracking():
    """
    Multiple sync cycles should correctly track balance changes.
    First cycle: SL hit on ETH, balance decreases.
    Second cycle: No more positions, balance stays the same.
    """
    now = datetime.now(timezone.utc)
    demo = DemoAccount(initial_balance=5000.0)
    add_demo_position(demo, side="LONG", entry=1660.0, sl=1625.0, tp=1730.0, now=now)
    executor = make_mock_executor([])
    prices = {"ETHUSDT": 1620.0}

    # Cycle 1: SL hit
    result1 = await sync_positions(demo, executor, latest_prices=prices, current_time=now)
    assert result1.positions_closed_from_exchange_sl == 1
    assert len(demo.open_positions) == 0
    balance_after_sl = demo.balance
    assert balance_after_sl < 5000.0

    # Cycle 2: No positions to reconcile
    result2 = await sync_positions(demo, executor, latest_prices=prices, current_time=now)
    assert result2.demo_positions_checked == 0
    assert demo.balance == balance_after_sl  # Balance unchanged


@pytest.mark.asyncio
async def test_sync_position_still_on_exchange_no_action():
    """
    If position exists on BOTH DemoAccount and exchange with matching qty/side,
    sync should NOT close the position.
    """
    now = datetime.now(timezone.utc)
    demo = DemoAccount(initial_balance=5000.0)
    add_demo_position(demo, side="LONG", entry=1660.0, sl=1625.0, tp=1730.0, qty=1.0, now=now)
    exchange_pos = make_exchange_pos(contracts=1.0, entry=1660.0)
    executor = make_mock_executor([exchange_pos])
    prices = {"ETHUSDT": 1665.0}

    result = await sync_positions(demo, executor, latest_prices=prices, current_time=now)

    assert "ETHUSDT" in demo.open_positions
    assert result.positions_closed_from_exchange_sl == 0
    assert result.positions_closed_from_exchange_tp == 0
    assert result.positions_closed_from_exchange_manual == 0
    assert len(result.discrepancies) == 0
