"""
TradingOrchestrator — Unified Signal Pipeline.

Single entry point for the entire trading pipeline:
  1. Run ICT pattern detection on candle data
  2. Detect Combo 521 sweep+FVG patterns
  3. Feed signals to DemoAccount (in-memory paper trading)
  4. Mirror opened positions to Binance Futures exchange
  5. Send Discord notifications for newly opened trades
  6. Reconcile positions periodically (SL/TP hit on exchange → close in DemoAccount)

All coordination lives here.
"""

from typing import Dict, List, Optional, Set
from datetime import datetime, timezone
from loguru import logger
import polars as pl

from ict_engine.market_structure import MarketStructure
from ict_engine.fvg import FVGDetector
from ict_engine.liquidity import LiquidityDetector
from ict_engine.premium_discount import PremiumDiscountDetector
from signal_engine.combo521 import Combo521Detector
from demo_account import DemoAccount
from execution.executor import LiveExecutor
from discord.bot import DiscordBot


class TradingOrchestrator:
    """
    Unified signal pipeline orchestrator.

    Usage:
        orch = TradingOrchestrator(demo_account, live_executor, discord_bot)
        await orch.process_candle_close(symbol, df_5m, df_15m, latest_prices, htf_bias)

    The orchestrator manages:
      - Necessary ICT modules (Swings, FVG, Liquidity, PD)
      - Signal generation from incoming candle data
      - DemoAccount state updates
      - Exchange order mirroring
      - Discord notifications
    """

    def __init__(
        self,
        demo_account: DemoAccount,
        live_executor: Optional[LiveExecutor] = None,
        discord_bot: Optional[DiscordBot] = None,
        kill_zones_enabled: bool = False,
    ):
        self.demo = demo_account
        self.executor = live_executor
        self.discord = discord_bot
        self.kill_zones_enabled = kill_zones_enabled

        # ── ICT detectors (shared, created once) ─────────────────────
        self.ict_ms = MarketStructure(n=2)  # swing_lookback=2 for Combo 521
        self.ict_fvg = FVGDetector()
        self.ict_liquidity = LiquidityDetector(atr_threshold=0.10)
        self.ict_pd = PremiumDiscountDetector()
        self.combo521 = Combo521Detector(
            swing_lookback=2,
            max_bars_after_sweep=20,
            min_gap_pct=0.05,
            entry_mode="proximal",
        )

        # ── State tracking ───────────────────────────────────────────
        self._notified_symbols: Set[str] = set()  # Discord-already-sent per cycle
        self.last_error: Optional[str] = None
        self.last_error_time: Optional[datetime] = None

        # ── Metrics ──────────────────────────────────────────────────
        self.total_signals_generated: int = 0
        self.total_signals_kept: int = 0
        self.total_trades_executed: int = 0
        self.cycle_count: int = 0

    # ── Public API ────────────────────────────────────────────────────

    async def process_candle_close(
        self,
        symbol: str,
        df_5m: pl.DataFrame,
        df_15m: pl.DataFrame,
        current_prices: Dict[str, float],
        htf_bias: str,
    ) -> Dict:
        """
        Called every time a new 5m candle closes.

        Steps:
          1. Run Combo 521 ICT pipeline on 5m data (swing n=2, FVG, liquidity, PD)
          2. Detect sweep+FVG pattern via Combo521Detector
          3. Feed qualifying signals to DemoAccount
          4. Mirror any newly opened positions to Binance
          5. Send Discord notification per new position

        No HTF bias filter, no scoring — pure sweep+FVG pattern detection.

        Returns a summary dict for API consumption.
        """
        self.cycle_count += 1
        self._notified_symbols.clear()

        if df_5m.is_empty() or len(df_5m) < 30:
            return self._build_summary(symbol, [], current_prices)

        # ── Combo 521 ICT pipeline on 5m data ────────────────────────
        df = df_5m.clone()
        df = self.ict_ms.detect_swings(df)
        df = self.ict_fvg.detect_fvgs(df)
        df = self.ict_liquidity.detect_all(df)
        df = self.ict_pd.compute_zones(df)

        # ── Detect Combo 521 patterns ────────────────────────────────
        current_idx = len(df) - 1  # the just-closed candle is the last row
        all_signals = self.combo521.detect(df, current_idx=current_idx, symbol=symbol)

        if not all_signals:
            return self._build_summary(symbol, [], current_prices)

        self.total_signals_generated += len(all_signals)

        # ── Assign IDs ───────────────────────────────────────────────
        for i, s in enumerate(all_signals):
            s["id"] = self.cycle_count * 100 + i

        self.total_signals_kept += len(all_signals)

        # ── Attach live prices ───────────────────────────────────────
        for s in all_signals:
            sym = s.get("symbol", "")
            live = current_prices.get(sym, 0.0)
            if live > 0 and s.get("price", 0) > 0:
                s["trigger_price"] = s["price"]
                s["price"] = live

        # ── Kill zones override (when disabled) ─────────────────────
        if not self.kill_zones_enabled:
            for s in all_signals:
                s["in_kill_zone"] = True

        # ── STEP B: Feed to DemoAccount ──────────────────────────────
        symbols_before: Set[str] = set(self.demo.open_positions.keys())
        self.demo.process_signals(all_signals, current_prices)

        # ── STEP C: Mirror new positions to Binance exchange ─────────
        if self.executor and self.executor.exchange:
            for sym, pos in list(self.demo.open_positions.items()):
                if sym in symbols_before:
                    continue

                try:
                    has_pos = await self.executor.has_position(sym)
                    if has_pos:
                        logger.info(f"[Orch][{sym}] Position already on exchange, skipping mirror")
                        continue
                except Exception:
                    pass

                try:
                    await self.executor.place_order(
                        symbol=sym,
                        side=pos.side,
                        qty=pos.quantity,
                        price=pos.entry_price,
                        sl=pos.stop_loss,
                        tp=pos.take_profit,
                        use_limit_order=False,  # market entry so orders fill immediately
                    )
                    self.total_trades_executed += 1
                    logger.info(
                        f"[Orch][{sym}] Mirrored {pos.side} to Binance: "
                        f"entry={pos.entry_price:.2f} SL={pos.stop_loss:.2f} TP={pos.take_profit:.2f}"
                    )
                except Exception as e:
                    logger.warning(f"[Orch][{sym}] Mirror to exchange failed: {e}")

        # ── STEP D: Discord notifications for newly opened trades ──
        if self.discord:
            for s in all_signals:
                sym = s.get("symbol", "")
                if sym in self.demo.open_positions and sym not in symbols_before and sym not in self._notified_symbols:
                    self._notified_symbols.add(sym)
                    try:
                        s["trigger_price"] = s.get("trigger_price", s.get("price", 0))
                        await self.discord.send_signal(s)
                    except Exception as e:
                        logger.warning(f"[Orch][{sym}] Discord send failed: {e}")

        return self._build_summary(symbol, all_signals, current_prices)

    # ── Position Reconciliation ──────────────────────────────────────

    async def sync_exchange_positions(
        self,
        current_prices: Dict[str, float],
    ) -> Dict:
        """
        Reconcile DemoAccount's open positions with actual Binance positions.
        """
        from execution.sync_worker import sync_positions

        if not self.executor or not self.executor.exchange:
            return {"status": "no_exchange", "errors": ["No exchange connection available"]}

        result = await sync_positions(
            demo_account=self.demo,
            live_executor=self.executor,
            latest_prices=current_prices,
        )

        return {
            "timestamp": result.timestamp.isoformat(),
            "demo_positions_checked": result.demo_positions_checked,
            "exchange_positions_checked": result.exchange_positions_checked,
            "positions_closed_sl": result.positions_closed_from_exchange_sl,
            "positions_closed_tp": result.positions_closed_from_exchange_tp,
            "positions_closed_manual": result.positions_closed_from_exchange_manual,
            "discrepancies": result.discrepancies,
            "errors": result.errors,
        }

    # ── Reset ────────────────────────────────────────────────────────

    async def reset_all(self, initial_balance: float = 5000.0):
        """Reset DemoAccount, caches, and counters to start fresh."""
        self.demo.open_positions.clear()
        self.demo.closed_trades.clear()
        self.demo.balance = initial_balance
        self.demo.equity = initial_balance
        self.demo._peak_balance = initial_balance
        self.demo._daily_pnl = 0.0
        self.demo._last_sl.clear()
        self.demo._last_trade_date = datetime.now(timezone.utc).date()

        # Clear DB
        if self.demo.db:
            await self.demo.db.clear_all_data()

        self.total_signals_generated = 0
        self.total_signals_kept = 0
        self.total_trades_executed = 0
        self._notified_symbols.clear()
        logger.info(f"[Orch] Reset complete — DemoAccount reset to ${initial_balance:.2f}")

    # ── Internal Helpers ─────────────────────────────────────────────

    def _build_summary(
        self,
        symbol: str,
        signals: List[Dict],
        current_prices: Dict[str, float],
    ) -> Dict:
        """Build a summary dict for the API to consume."""
        open_positions = DemoAccount.enrich_positions(
            self.demo.get_open_positions_list(), dict(current_prices),
        )

        perf = self.demo.get_performance()
        perf["open_positions_count"] = len(open_positions)
        perf["open_positions"] = open_positions

        return {
            "symbol": symbol,
            "signals_generated": len(signals),
            "signals": signals,
            "open_positions": open_positions,
            "open_positions_count": len(open_positions),
            "trades": self.demo.get_closed_trades_list(500),
            "performance": perf,
        }
