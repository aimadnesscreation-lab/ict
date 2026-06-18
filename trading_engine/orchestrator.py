"""
TradingOrchestrator — Unified Signal Pipeline.

Single entry point for the entire trading pipeline:
  1. Generate ICT signals from candle data
  2. Filter SHORT signals (spot-only — Binance Spot only supports LONG)
  3. Feed signals to DemoAccount (in-memory paper trading)
  4. Mirror opened positions to Binance Spot exchange
  5. Send Discord notifications for newly opened trades
  6. Reconcile positions periodically (SL/TP hit on exchange → close in DemoAccount)

No more scattered logic across api/main.py, signal_engine, sync_worker, etc.
All coordination lives here.
"""

from typing import Dict, List, Optional, Set
from datetime import datetime, timezone
from loguru import logger
import polars as pl

from ict_engine.market_structure import MarketStructure
from ict_engine.fvg import FVGDetector
from ict_engine.order_blocks import OrderBlockDetector
from ict_engine.liquidity import LiquidityDetector
from ict_engine.sessions import SessionDetector
from ict_engine.premium_discount import PremiumDiscountDetector
from signal_engine.engine import SignalEngine
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
      - All 7 ICT modules (shared instances, created once)
      - Signal generation from incoming candle data
      - Spot-mode SHORT signal filtering (always on)
      - DemoAccount state updates
      - Exchange order mirroring
      - Discord notifications
    """

    def __init__(
        self,
        demo_account: DemoAccount,
        live_executor: Optional[LiveExecutor] = None,
        discord_bot: Optional[DiscordBot] = None,
    ):
        self.demo = demo_account
        self.executor = live_executor
        self.discord = discord_bot

        # ── ICT detectors (shared, created once) ─────────────────────
        self.ict_ms = MarketStructure(n=3)
        self.ict_fvg = FVGDetector()
        self.ict_ob = OrderBlockDetector()
        self.ict_liquidity = LiquidityDetector(atr_threshold=0.10)
        self.ict_sessions = SessionDetector()
        self.ict_pd = PremiumDiscountDetector()
        self.signal_engine = SignalEngine()

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
          1. Run ICT pipeline on 5m and 15m data
          2. Generate signals via SignalEngine
          3. Spot-only filter — remove ALL SHORT signals
          4. Feed qualifying signals to DemoAccount
          5. Mirror any newly opened positions to Binance
          6. Send Discord notification per new position

        Returns a summary dict for API consumption.
        """
        self.cycle_count += 1
        self._notified_symbols.clear()

        all_signals: List[Dict] = []
        timeframes_to_check = ["5m", "15m"]

        for tf in timeframes_to_check:
            df = df_5m if tf == "5m" else df_15m
            if df.is_empty() or len(df) < 20:
                continue

            # ── Full ICT pipeline ────────────────────────────────────
            df = self.ict_ms.detect_swings(df)
            df = self.ict_ms.detect_bos_mss(df)
            df = self.ict_fvg.detect_fvgs(df)
            df = self.ict_ob.detect_order_blocks(df)
            df = self.ict_liquidity.detect_all(df)
            df = self.ict_sessions.detect_sessions(df)
            df = self.ict_pd.compute_zones(df)

            # Extract MSS and sweep from latest data
            mss_type = None
            if "mss" in df.columns:
                latest_mss = df["mss"].drop_nulls().tail(1)
                if len(latest_mss) > 0:
                    mss_type = latest_mss[0]

            sweep_type = None
            if "liquidity_sweep_type" in df.columns:
                latest_sweep = df["liquidity_sweep_type"].drop_nulls().tail(1)
                if len(latest_sweep) > 0:
                    sweep_type = latest_sweep[0]

            # Generate signal
            signal = self.signal_engine.generate_signal(
                df,
                mss_type=mss_type,
                sweep_type=sweep_type,
                timeframe=tf,
                htf_bias=htf_bias,
            )
            signal["symbol"] = symbol

            # Attach ATR for position sizing
            if "atr" in df.columns:
                latest_atr = df["atr"].tail(1).to_list()
                signal["atr"] = latest_atr[0] if latest_atr and latest_atr[0] is not None else 0.0
            else:
                signal["atr"] = 0.0

            # Confidence from score
            score = signal.get("score", 0)
            if score >= 80:
                signal["confidence"] = 0.92
            elif score >= 60:
                signal["confidence"] = 0.75
            elif score >= 40:
                signal["confidence"] = 0.55
            elif score >= 20:
                signal["confidence"] = 0.35
            else:
                signal["confidence"] = 0.15

            all_signals.append(signal)

        if not all_signals:
            return self._build_summary(symbol, [], current_prices)

        self.total_signals_generated += len(all_signals)

        # ── HTF alignment filter ─────────────────────────────────────
        if htf_bias != "neutral":
            all_signals = [s for s in all_signals if s.get("htf_aligned", True)]
        else:
            all_signals = []

        if not all_signals:
            return self._build_summary(symbol, [], current_prices)

        # ── Assign IDs ───────────────────────────────────────────────
        for i, s in enumerate(all_signals):
            s["id"] = self.cycle_count * 100 + i

        # ── STEP A: SPOT-ONLY FILTER ─────────────────────────────────
        # Binance Spot only supports LONG. Remove ALL SHORT signals here
        # so neither DemoAccount nor exchange ever sees them.
        before_filter = len(all_signals)
        all_signals = [s for s in all_signals if not s.get("signal_type", "").startswith("SELL")]
        filtered_count = before_filter - len(all_signals)
        if filtered_count > 0:
            logger.info(f"[Orch][{symbol}] Filtered {filtered_count} SHORT signal(s) — spot only supports LONG")

        if not all_signals:
            return self._build_summary(symbol, [], current_prices)

        self.total_signals_kept += len(all_signals)

        # ── Attach live prices ───────────────────────────────────────
        for s in all_signals:
            sym = s.get("symbol", "")
            live = current_prices.get(sym, 0.0)
            if live > 0 and s.get("price", 0) > 0:
                s["trigger_price"] = s["price"]
                s["price"] = live

        # ── STEP B: Feed to DemoAccount ──────────────────────────────
        symbols_before: Set[str] = set(self.demo.open_positions.keys())
        self.demo.process_signals(all_signals, current_prices)

        # ── STEP C: Mirror new positions to Binance exchange ─────────
        if self.executor and self.executor.exchange:
            for sym, pos in list(self.demo.open_positions.items()):
                # Only mirror positions that were JUST opened (not in symbols_before)
                if sym in symbols_before:
                    continue

                # Double-check: exchange already has a position for this symbol
                try:
                    has_pos = await self.executor.has_position(sym)
                    if has_pos:
                        logger.info(f"[Orch][{sym}] Position already on exchange, skipping mirror")
                        continue
                except Exception:
                    pass  # If check fails, try to mirror anyway

                try:
                    await self.executor.place_order(
                        symbol=sym,
                        side=pos.side,
                        qty=pos.quantity,
                        price=pos.entry_price,
                        sl=pos.stop_loss,
                        tp=pos.take_profit,
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
                # Only notify if this signal opened a new position AND we haven't notified for this symbol yet
                if sym in self.demo.open_positions and sym not in symbols_before and sym not in self._notified_symbols:
                    self._notified_symbols.add(sym)
                    try:
                        # Enrich the signal with trigger price for the embed
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
        Handles: SL/TP hit on exchange, manual closes, partial fills.

        This is the sync_worker logic, embedded directly in the orchestrator
        so there's no cross-module coordination needed.
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
        open_positions = self.demo.get_open_positions_list()
        for pos in open_positions:
            sym = pos["symbol"]
            cur_price = current_prices.get(sym, 0.0)
            if cur_price > 0:
                pos["current_price"] = round(cur_price, 2)
                if pos["side"] == "LONG":
                    pos["unrealized_pnl"] = round((cur_price - pos["entry_price"]) * pos["quantity"], 2)
                else:
                    pos["unrealized_pnl"] = round((pos["entry_price"] - cur_price) * pos["quantity"], 2)

        # Build performance dict with open positions — api/main.py stores
        # the "performance" key in _performance_cache. The /demo/account
        # endpoint reads open_positions from it, so we need those keys here.
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
