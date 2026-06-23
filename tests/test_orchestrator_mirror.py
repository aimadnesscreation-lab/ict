"""
Tests for TradingOrchestrator mirror logic — DemoAccount to LiveExecutor.

Covers:
  - Signal → DemoAccount position → mirror to LiveExecutor
  - Already-mirrored positions are skipped
  - No executor configured → graceful skip
  - Kill zones enabled/disabled behavior
  - HTF alignment filtering
"""

from __future__ import annotations

import pytest
import polars as pl
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List, Optional

from demo_account import DemoAccount
from execution.executor import LiveExecutor
from trading_engine.orchestrator import TradingOrchestrator


# ── Helpers ──────────────────────────────────────────────────────────


def make_5m_candles(n: int = 40) -> pl.DataFrame:
    """
    Create a basic 5m candle DataFrame with a bullish trend.
    The trend should generate ICT signals (swings, FVG, etc.).
    """
    base = 1650.0
    rows = []
    for i in range(n):
        t = datetime(2026, 6, 23, 0, 0, 0, tzinfo=timezone.utc)
        from datetime import timedelta
        ts = t + timedelta(minutes=5 * i)
        # Bullish drift with some noise
        drift = i * 0.8  # Upward trend
        noise = (i % 5 - 2) * 0.5  # Small oscillations
        o = base + drift + noise
        c = base + drift + 0.5 + noise
        h = max(o, c) + 1.0
        l = min(o, c) - 0.5
        rows.append({
            "timestamp": ts,
            "open": o, "high": h, "low": l, "close": c,
            "volume": 100.0 + i * 2,
        })
    return pl.DataFrame(rows)


def make_mock_executor() -> AsyncMock:
    """Create a mocked LiveExecutor that tracks calls to place_order."""
    executor = AsyncMock(spec=LiveExecutor)
    executor.exchange = MagicMock()  # Non-None to bypass guards
    executor.has_position = AsyncMock(return_value=False)
    executor.place_order = AsyncMock(return_value={"id": "mock_order_1", "filled": 0.1, "price": 1660.0})
    executor.get_balance = AsyncMock(return_value=5000.0)
    executor.get_total_balance = AsyncMock(return_value=5000.0)
    executor.get_open_positions = AsyncMock(return_value=[])
    executor.set_leverage = AsyncMock()
    executor.cancel_all_orders = AsyncMock()
    return executor


def make_orchestrator(
    demo: DemoAccount | None = None,
    executor: AsyncMock | None = None,
    kill_zones_enabled: bool = True,
) -> TradingOrchestrator:
    """Create a TradingOrchestrator with optional overrides."""
    return TradingOrchestrator(
        demo_account=demo or DemoAccount(initial_balance=5000.0),
        live_executor=executor or make_mock_executor(),
        discord_bot=None,
        kill_zones_enabled=kill_zones_enabled,
    )


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mirror_opens_position_with_sufficient_signal():
    """
    A strong bullish signal should open a DemoAccount LONG position
    and mirror it to the exchange via LiveExecutor.place_order().
    """
    demo = DemoAccount(
        initial_balance=5000.0,
        risk_per_trade_pct=1.0,
        max_open_positions=3,
        sl_multiplier=1.5,
        symbol_min_scores={"ETHUSDT": 40},
        reentry_cooldown_minutes=0,
    )
    executor = make_mock_executor()
    orch = make_orchestrator(demo=demo, executor=executor, kill_zones_enabled=True)
    df_5m = make_5m_candles()

    # Patch signal_engine.generate_signal to return a strong BUY
    # The ICT detectors still run on real candle data, then our patched
    # generate_signal produces the predetermined signal.
    signal = {
        "symbol": "ETHUSDT", "signal_type": "STRONG_BUY", "score": 85,
        "bullish_score": 80, "bearish_score": 10, "net_score": 70,
        "price": 1660.0, "timeframe": "5m", "bias": "bullish",
        "htf_bias": "bullish", "htf_aligned": True, "in_kill_zone": True,
        "atr": 15.0, "timestamp": datetime.now(timezone.utc),
        "details": {},
    }

    with patch.object(orch.signal_engine, "generate_signal", return_value=signal):
        result = await orch.process_candle_close(
            symbol="ETHUSDT",
            df_5m=df_5m,
            df_15m=pl.DataFrame(),
            current_prices={"ETHUSDT": 1660.0},
            htf_bias="bullish",
        )

    # Verify DemoAccount opened a position
    assert "ETHUSDT" in demo.open_positions
    pos = demo.open_positions["ETHUSDT"]
    assert pos.side == "LONG"
    assert pos.quantity > 0

    # Verify LiveExecutor.place_order was called with correct params
    executor.place_order.assert_awaited_once()
    call_kwargs = executor.place_order.await_args[1]
    assert call_kwargs["symbol"] == "ETHUSDT"
    assert call_kwargs["side"] == "LONG"
    assert call_kwargs["qty"] > 0
    assert call_kwargs["sl"] < call_kwargs["price"] < call_kwargs["tp"]


@pytest.mark.asyncio
async def test_mirror_skips_already_mirrored():
    """
    If exchange already has a position for the symbol, mirror is skipped.
    Tests through the real process_candle_close with has_position=True.
    """
    demo = DemoAccount(
        initial_balance=5000.0,
        risk_per_trade_pct=1.0,
        max_open_positions=3,
        sl_multiplier=1.5,
        symbol_min_scores={"ETHUSDT": 40},
        reentry_cooldown_minutes=0,
    )
    executor = make_mock_executor()
    executor.has_position = AsyncMock(return_value=True)  # Already on exchange
    orch = make_orchestrator(demo=demo, executor=executor)
    df_5m = make_5m_candles()

    signal = {
        "symbol": "ETHUSDT", "signal_type": "STRONG_BUY", "score": 85,
        "bullish_score": 80, "bearish_score": 10, "net_score": 70,
        "price": 1660.0, "timeframe": "5m", "bias": "bullish",
        "htf_bias": "bullish", "htf_aligned": True, "in_kill_zone": True,
        "atr": 15.0, "timestamp": datetime.now(timezone.utc),
        "details": {},
    }

    with patch.object(orch.signal_engine, "generate_signal", return_value=signal):
        result = await orch.process_candle_close(
            symbol="ETHUSDT",
            df_5m=df_5m,
            df_15m=pl.DataFrame(),
            current_prices={"ETHUSDT": 1660.0},
            htf_bias="bullish",
        )

    # DemoAccount should have opened the position (signal passes all filters)
    assert "ETHUSDT" in demo.open_positions
    # But LiveExecutor.place_order should NOT have been called
    # because has_position returned True (position already on exchange)
    executor.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_mirror_no_executor_skips_gracefully():
    """
    When no LiveExecutor is configured, the orchestrator should
    skip the mirror step without errors.
    """
    demo = DemoAccount(initial_balance=5000.0, symbol_min_scores={"ETHUSDT": 40})
    orch = TradingOrchestrator(
        demo_account=demo,
        live_executor=None,  # No executor
        kill_zones_enabled=True,
    )

    df_5m = make_5m_candles()

    # Process candle close - should complete without error even with no executor
    signal = {
        "symbol": "ETHUSDT", "signal_type": "STRONG_BUY", "score": 85,
        "price": 1660.0, "atr": 15.0, "in_kill_zone": True,
        "timestamp": datetime.now(timezone.utc), "htf_aligned": True,
        "id": 1,
    }

    with patch.object(orch.signal_engine, "generate_signal", return_value=signal):
        result = await orch.process_candle_close(
            symbol="ETHUSDT",
            df_5m=df_5m,
            df_15m=pl.DataFrame(),
            current_prices={"ETHUSDT": 1660.0},
            htf_bias="bullish",
        )

    assert result is not None
    # Should still process signals and open DemoAccount positions
    assert "signals" in result


@pytest.mark.asyncio
async def test_kill_zones_disabled_allows_all_signals():
    """
    When kill_zones_enabled=False, signals outside kill zones should
    still be fed to DemoAccount.
    """
    demo = DemoAccount(
        initial_balance=5000.0,
        symbol_min_scores={"ETHUSDT": 40},
        reentry_cooldown_minutes=0,
    )
    orch = make_orchestrator(demo=demo, kill_zones_enabled=False)
    df_5m = make_5m_candles()

    # Signal outside kill zone
    signal = {
        "symbol": "ETHUSDT", "signal_type": "STRONG_BUY", "score": 85,
        "price": 1660.0, "atr": 15.0, "in_kill_zone": False,  # NOT in a kill zone
        "timestamp": datetime.now(timezone.utc), "htf_aligned": True,
        "id": 1,
    }

    with patch.object(orch.signal_engine, "generate_signal", return_value=signal):
        result = await orch.process_candle_close(
            symbol="ETHUSDT",
            df_5m=df_5m,
            df_15m=pl.DataFrame(),
            current_prices={"ETHUSDT": 1660.0},
            htf_bias="bullish",
        )

    # DemoAccount should have opened a position because kill_zones_enabled=False
    # overrides in_kill_zone to True before feeding to DemoAccount
    assert "ETHUSDT" in demo.open_positions


@pytest.mark.asyncio
async def test_kill_zones_enabled_blocks_outside_signals():
    """
    When kill_zones_enabled=True (default), signals outside kill zones
    should be rejected by DemoAccount.
    """
    demo = DemoAccount(
        initial_balance=5000.0,
        symbol_min_scores={"ETHUSDT": 40},
        reentry_cooldown_minutes=0,
    )
    orch = make_orchestrator(demo=demo, kill_zones_enabled=True)
    df_5m = make_5m_candles()

    # Signal outside kill zone
    signal = {
        "symbol": "ETHUSDT", "signal_type": "STRONG_BUY", "score": 85,
        "price": 1660.0, "atr": 15.0, "in_kill_zone": False,  # NOT in a kill zone
        "timestamp": datetime.now(timezone.utc), "htf_aligned": True,
        "id": 1,
    }

    with patch.object(orch.signal_engine, "generate_signal", return_value=signal):
        result = await orch.process_candle_close(
            symbol="ETHUSDT",
            df_5m=df_5m,
            df_15m=pl.DataFrame(),
            current_prices={"ETHUSDT": 1660.0},
            htf_bias="bullish",
        )

    # DemoAccount should NOT have opened a position because it's outside kill zone
    assert "ETHUSDT" not in demo.open_positions


@pytest.mark.asyncio
async def test_htf_misalignment_blocks_signal():
    """
    Signals that are not aligned with HTF bias should be filtered out
    before reaching DemoAccount.
    """
    demo = DemoAccount(
        initial_balance=5000.0,
        symbol_min_scores={"ETHUSDT": 40},
        reentry_cooldown_minutes=0,
    )
    orch = make_orchestrator(demo=demo, kill_zones_enabled=True)
    df_5m = make_5m_candles()

    # SELL signal with bullish HTF bias → not aligned → should be filtered
    signal = {
        "symbol": "ETHUSDT", "signal_type": "SELL", "score": 75,
        "price": 1660.0, "atr": 15.0, "in_kill_zone": True,
        "timestamp": datetime.now(timezone.utc), "htf_aligned": False,  # Misaligned!
        "id": 1,
    }

    with patch.object(orch.signal_engine, "generate_signal", return_value=signal):
        result = await orch.process_candle_close(
            symbol="ETHUSDT",
            df_5m=df_5m,
            df_15m=pl.DataFrame(),
            current_prices={"ETHUSDT": 1660.0},
            htf_bias="bullish",
        )

    # Signal should have been filtered out by HTF alignment check
    assert len(result.get("signals", [])) == 0
    assert "ETHUSDT" not in demo.open_positions


@pytest.mark.asyncio
async def test_risk_limits_block_over_trading():
    """
    DemoAccount should respect max_open_positions and max_daily_loss.
    """
    demo = DemoAccount(
        initial_balance=5000.0,
        risk_per_trade_pct=1.0,
        max_open_positions=1,  # Only 1 position at a time
        symbol_min_scores={"ETHUSDT": 40, "BTCUSDT": 40},
        reentry_cooldown_minutes=0,
    )
    orch = make_orchestrator(demo=demo, kill_zones_enabled=True)
    df_5m = make_5m_candles()
    timestamp = datetime.now(timezone.utc)

    # Signal 1: ETH LONG
    signal1 = {
        "symbol": "ETHUSDT", "signal_type": "STRONG_BUY", "score": 85,
        "price": 1660.0, "atr": 15.0, "in_kill_zone": True,
        "timestamp": timestamp, "htf_aligned": True, "id": 1,
    }

    with patch.object(orch.signal_engine, "generate_signal", return_value=signal1):
        result1 = await orch.process_candle_close(
            symbol="ETHUSDT", df_5m=df_5m, df_15m=pl.DataFrame(),
            current_prices={"ETHUSDT": 1660.0}, htf_bias="bullish",
        )
    assert "ETHUSDT" in demo.open_positions  # ETH opened

    # Signal 2: BTC LONG (should be blocked by max_open_positions=1)
    signal2 = {
        "symbol": "BTCUSDT", "signal_type": "STRONG_BUY", "score": 85,
        "price": 67000.0, "atr": 500.0, "in_kill_zone": True,
        "timestamp": timestamp, "htf_aligned": True, "id": 2,
    }

    with patch.object(orch.signal_engine, "generate_signal", return_value=signal2):
        result2 = await orch.process_candle_close(
            symbol="BTCUSDT", df_5m=df_5m, df_15m=pl.DataFrame(),
            current_prices={"BTCUSDT": 67000.0}, htf_bias="bullish",
        )
    assert "BTCUSDT" not in demo.open_positions  # BTC blocked
