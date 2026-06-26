"""
Demo Account — Stateful Forward Testing Engine.

Opens trades based on live signals, tracks open positions in memory,
checks SL/TP against current prices every cycle, and maintains
full trade history + performance metrics.

Rules:
  - 1% risk per trade (of current account balance)
  - 1:3 risk-reward (SL = 1× ATR, TP = 3× ATR) — configurable via tp_ratio
  - Trades signals that pass per-symbol min_score threshold (symbol_min_scores)
    or all signals from Combo 521 (which sets score=100 internally, bypassing scoring)
  - Long on BUY/STRONG_BUY, Short on SELL/STRONG_SELL
  - Max 1 open position per symbol (ignores weaker signals if already in)
  - Account starts at $5,000
"""

from typing import Dict, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass
from loguru import logger


@dataclass
class OpenPosition:
    symbol: str
    signal_type: str
    side: str  # "LONG" or "SHORT"
    entry_time: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: float  # units of the asset
    risk_amount: float  # dollar amount risked
    atr: float


@dataclass
class ClosedTrade:
    symbol: str
    signal_type: str
    side: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    quantity: float
    profit: float
    profit_pct: float
    rr: float
    result: str  # "WIN", "LOSS", "BREAK_EVEN"
    exit_reason: str  # "TAKE_PROFIT", "STOP_LOSS", "MANUAL"


class DemoAccount:
    def __init__(self, initial_balance: float = 5_000.0, risk_per_trade_pct: float = 1.0,
                 max_daily_loss_pct: float = 3.0, max_open_positions: int = 3,
                 sl_multiplier: float = 1.5,
                 reentry_cooldown_minutes: int = 60,
                 fixed_sl_pct: float = 0.0,
                 symbol_sl_multipliers: Optional[Dict[str, float]] = None,
                 symbol_min_scores: Optional[Dict[str, int]] = None,
                 spot_only: bool = False,
                 db_manager=None,
                 tiered_sizing: bool = False,
                 tp_ratio: float = 3.0):
        self.tp_ratio = tp_ratio
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.equity = initial_balance
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_open_positions = max_open_positions
        self.sl_multiplier = sl_multiplier
        self.reentry_cooldown_minutes = reentry_cooldown_minutes
        self.fixed_sl_pct = fixed_sl_pct
        self.symbol_sl_multipliers = symbol_sl_multipliers or {}  # per-symbol ATR multiplier overrides
        self.symbol_min_scores = symbol_min_scores or {}  # per-symbol score threshold overrides
        self.spot_only = spot_only  # If True, SKIP all SHORT signals (for Binance Spot)
        self.tiered_sizing = tiered_sizing  # If True, scale position size by signal score
        self.db = db_manager
        self.open_positions: Dict[str, OpenPosition] = {}  # keyed by symbol
        self.closed_trades: List[ClosedTrade] = []
        self._peak_balance = initial_balance
        self._daily_pnl = 0.0
        self._last_trade_date = datetime.now(timezone.utc).date()
        # Track last stop-loss for each symbol to prevent rapid re-entry
        self._last_sl: Dict[str, Dict] = {}  # {symbol: {"time": datetime, "side": str}}

    @property
    def daily_loss(self) -> float:
        """Return the absolute daily P&L (always positive) for API display.

        Internal circuit breaker logic uses `_daily_pnl` directly (negative when
        losing) so the max_daily_loss_pct limit works correctly.
        """
        return abs(self._daily_pnl)

    # ── Public API ────────────────────────────────────────────────────

    def process_signals(self, signals: List[Dict], current_prices: Dict[str, float],
                         current_time: Optional[datetime] = None) -> List[Dict]:
        """
        Main entry point — called every signal cycle.
        1. Reset daily P&L if a new UTC day has started
        2. Check open positions against current prices → close any that hit SL/TP
        3. Open new positions for strong signals not already in a position

        Args:
            signals: List of signal dicts
            current_prices: Dict of {symbol: current_price}
            current_time: Timestamp override for backtesting (uses datetime.now(timezone.utc) in live mode)

        Returns the list of trades that were closed this cycle (for logging).
        """
        now = current_time if current_time is not None else datetime.now(timezone.utc)

        # Reset daily P&L on UTC day change — prevents permanent lockout
        today = now.date()
        if today != self._last_trade_date:
            logger.info(f"Daily P&L reset: {self._daily_pnl:.2f} → 0.00 (new trading day)")
            self._daily_pnl = 0.0
            self._last_trade_date = today

        freshly_closed: List[Dict] = []

        # Step 1: Check existing positions
        for symbol in list(self.open_positions.keys()):
            pos = self.open_positions[symbol]
            current_price = current_prices.get(symbol)
            if current_price is None:
                continue

            trade = self._check_position(pos, current_price, now)
            if trade is not None:
                freshly_closed.append(trade)

        # Step 2: Open new positions for strong signals
        for signal in signals:
            symbol = signal.get("symbol", "")
            signal_type = signal.get("signal_type", "NEUTRAL")
            score = signal.get("score", 0)
            price = signal.get("price", 0)
            atr = signal.get("atr", 0)
            timestamp = signal.get("timestamp")

            # Only act on high-conviction signals in kill zone (match Discord criteria)
            # Default score ≥ 80, with per-symbol overrides via symbol_min_scores
            min_score = self.symbol_min_scores.get(symbol, 80)
            if score < min_score or not signal.get("in_kill_zone", False):
                continue

            # Skip if already in a position for this symbol
            if symbol in self.open_positions:
                continue

            # Risk limit checks
            # 1. Max open positions
            if len(self.open_positions) >= self.max_open_positions:
                logger.info(f"Risk limit: max {self.max_open_positions} open positions reached, skipping {symbol} {signal_type}")
                continue

            # 2. Max daily loss
            if self._daily_pnl <= -(self.initial_balance * self.max_daily_loss_pct / 100):
                logger.warning(f"Risk limit: daily loss of {self._daily_pnl:.2f} exceeds {self.max_daily_loss_pct}% cap, no more trades today")
                continue

            # Determine side
            if "BUY" in signal_type:
                side = "LONG"
            elif "SELL" in signal_type:
                side = "SHORT"
                # Spot-only mode: reject ALL SHORT signals
                if self.spot_only:
                    logger.info(f"Spot-only: skipping SHORT {symbol} {signal_type} — spot only supports LONG")
                    continue
            else:
                continue

            # Same-direction re-entry cooldown after stop loss
            # Prevents the death spiral: SL → immediate re-entry → SL → re-entry
            # Must be after side determination to avoid UnboundLocalError
            if (self.reentry_cooldown_minutes > 0 and
                symbol in self._last_sl and
                self._last_sl[symbol]["side"] == side):
                last_sl = self._last_sl[symbol]
                mins_since = (now - last_sl["time"]).total_seconds() / 60
                if mins_since < self.reentry_cooldown_minutes:
                    logger.info(
                        f"Cooldown: skipping {symbol} {signal_type} — "
                        f"SL was {mins_since:.0f}m ago (need {self.reentry_cooldown_minutes}m)"
                    )
                    continue

            # Use ATR (fallback to 1% of price if unavailable)
            atr_value = atr if atr > 0 else price * 0.01
            if atr_value <= 0:
                continue

            new_pos = self._open_trade(symbol, signal_type, side, price, atr_value, timestamp, score=score)
            if new_pos:
                logger.info(
                    f"Demo opened {side} {symbol} @ {price:.2f} "
                    f"SL={new_pos.stop_loss:.2f} TP={new_pos.take_profit:.2f} "
                    f"Qty={new_pos.quantity:.4f} Risk=${new_pos.risk_amount:.2f}"
                )

        return freshly_closed

    def get_performance(self) -> Dict:
        """Return performance metrics matching the /performance endpoint shape."""
        if not self.closed_trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "total_profit": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "capital_remaining": self.balance,
                "avg_rr": 0.0,
            }

        wins = [t for t in self.closed_trades if t.result == "WIN"]
        losses = [t for t in self.closed_trades if t.result == "LOSS"]
        total_profit = sum(t.profit for t in self.closed_trades)
        win_rate = len(wins) / len(self.closed_trades)
        gross_profits = sum(t.profit for t in wins)
        gross_losses = abs(sum(t.profit for t in losses))
        profit_factor = gross_profits / gross_losses if gross_losses > 0 else (999 if gross_profits > 0 else 0)
        avg_rr = sum(t.rr for t in self.closed_trades) / len(self.closed_trades)

        # Max drawdown
        equity = self.initial_balance
        peak = equity
        max_dd = 0.0
        for t in self.closed_trades:
            equity += t.profit
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        return {
            "total_trades": len(self.closed_trades),
            "win_rate": round(win_rate, 4),
            "total_profit": round(total_profit, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown": round(max_dd, 4),
            "capital_remaining": round(self.balance, 2),
            "avg_rr": round(avg_rr, 2),
            "total_wins": len(wins),
            "total_losses": len(losses),
            "peak_balance": round(self._peak_balance, 2),
            "current_drawdown_pct": round(
                max(0, (self._peak_balance - self.balance) / self._peak_balance * 100), 2
            ) if self._peak_balance > 0 else 0,
        }

    def get_open_positions_list(self) -> List[Dict]:
        """Return open positions in API-friendly format (raw prices, caller handles precision)."""
        return [
            {
                "symbol": pos.symbol,
                "side": pos.side,
                "signal_type": pos.signal_type,
                "entry_time": pos.entry_time.isoformat() if hasattr(pos.entry_time, "isoformat") else str(pos.entry_time),
                "entry_price": round(pos.entry_price, 6),
                "current_price": 0.0,  # caller should fill this
                "stop_loss": round(pos.stop_loss, 6),
                "take_profit": round(pos.take_profit, 6),
                "quantity": round(pos.quantity, 6),
                "risk_amount": round(pos.risk_amount, 2),
                "unrealized_pnl": 0.0,  # caller should fill
            }
            for pos in self.open_positions.values()
        ]

    @staticmethod
    def enrich_positions(open_positions: List[Dict], latest_prices: Dict[str, float]) -> List[Dict]:
        """Fill current_price and unrealized_pnl for each open position dict.

        Mutates the position dicts in-place and returns the list for chaining.
        Each position dict must have: symbol, side, entry_price, quantity.
        """
        for pos in open_positions:
            sym = pos["symbol"]
            cur_price = latest_prices.get(sym, 0.0)
            if cur_price > 0:
                pos["current_price"] = round(cur_price, 2)
                if pos["side"] == "LONG":
                    pos["unrealized_pnl"] = round((cur_price - pos["entry_price"]) * pos["quantity"], 2)
                else:
                    pos["unrealized_pnl"] = round((pos["entry_price"] - cur_price) * pos["quantity"], 2)
        return open_positions

    def get_closed_trades_list(self, limit: int = 200) -> List[Dict]:
        """Return closed trades in API-friendly format (newest first)."""
        trades = sorted(self.closed_trades, key=lambda t: t.exit_time, reverse=True)[:limit]
        return [
            {
                "symbol": t.symbol,
                "signal_type": t.signal_type,
                "side": t.side,
                "entry_time": t.entry_time.isoformat() if hasattr(t.entry_time, "isoformat") else str(t.entry_time),
                "exit_time": t.exit_time.isoformat() if hasattr(t.exit_time, "isoformat") else str(t.exit_time),
                "entry_price": round(t.entry_price, 2),
                "exit_price": round(t.exit_price, 2),
                "stop_loss": round(t.stop_loss, 2),
                "take_profit": round(t.take_profit, 2),
                "quantity": round(t.quantity, 6),
                "profit": round(t.profit, 2),
                "profit_pct": round(t.profit_pct, 4),
                "rr": round(t.rr, 2),
                "result": t.result,
                "exit_reason": t.exit_reason,
            }
            for t in trades
        ]

    def restore_state(self, balance: float, peak_balance: float, 
                      positions: List[Dict], trades: List[Dict]):
        """Recover state from database on startup."""
        self.balance = balance
        self.equity = balance
        self._peak_balance = peak_balance
        
        # Restore positions
        for p in positions:
            p.pop('_sa_instance_state', None)
            symbol = p['symbol']
            self.open_positions[symbol] = OpenPosition(**p)
            
        # Restore trades
        for t in trades:
            t.pop('_sa_instance_state', None)
            self.closed_trades.append(ClosedTrade(**t))
            
        logger.info(f"DemoAccount restored: ${balance:.2f} balance, {len(positions)} positions, {len(trades)} trades.")

    def get_account_summary(self) -> Dict:
        """Return account overview for the dashboard."""
        return {
            "balance": round(self.balance, 2),
            "equity": round(self._compute_equity({}), 2),
            "initial_balance": self.initial_balance,
            "open_positions": len(self.open_positions),
            "total_trades": len(self.closed_trades),
            "total_profit": round(sum(t.profit for t in self.closed_trades), 2),
            "win_rate": round(
                len([t for t in self.closed_trades if t.result == "WIN"]) / len(self.closed_trades), 4
            ) if self.closed_trades else 0,
            "peak_balance": round(self._peak_balance, 2),
            "current_drawdown_pct": round(
                max(0, (self._peak_balance - self.balance) / self._peak_balance * 100), 2
            ) if self._peak_balance > 0 else 0,
        }

    # ── Internal ──────────────────────────────────────────────────────

    def _open_trade(self, symbol: str, signal_type: str, side: str,
                    price: float, atr_value: float, timestamp, score: int = 0) -> Optional[OpenPosition]:
        """Open a new position with 1% risk, tp_ratio RR (default 1:3).

        Three modes:
          1. Fixed percentage (if fixed_sl_pct > 0):
             SL = fixed_sl_pct% from entry, TP = tp_ratio × SL distance
             e.g. fixed_sl_pct=1.0 → SL 1% away, TP 3% away (with tp_ratio=3)
          2. ATR-based (default):
             Uses per-symbol multiplier from symbol_sl_multipliers if available,
             otherwise falls back to the default sl_multiplier.
             SL = multiplier × ATR, TP = tp_ratio × SL distance
          3. Tiered sizing (if tiered_sizing is True):
             Scales risk based on signal score:
               score < 70: 0.5x base risk
               score 70-79: 0.75x base risk
               score 80-89: 1.0x base risk (normal)
               score 90+: 1.5x base risk
        """
        if self.fixed_sl_pct > 0:
            # Fixed percentage mode: SL = N% from entry, TP = 2× that
            sl_distance = price * (self.fixed_sl_pct / 100)
        else:
            # ATR-based mode: use per-symbol override if available, else default
            effective_mult = self.symbol_sl_multipliers.get(symbol, self.sl_multiplier)
            sl_distance = atr_value * effective_mult
        tp_distance = sl_distance * self.tp_ratio  # Configurable R-multiple TP

        if side == "LONG":
            stop_loss = price - sl_distance
            take_profit = price + tp_distance
        else:
            stop_loss = price + sl_distance
            take_profit = price - tp_distance

        risk_per_unit = abs(price - stop_loss)
        if risk_per_unit <= 0:
            return None

        # Risk 1% of current balance (adjustable via tiered sizing)
        if self.tiered_sizing and score > 0:
            if score >= 90:
                sizing_mult = 1.5
            elif score >= 80:
                sizing_mult = 1.0
            elif score >= 70:
                sizing_mult = 0.75
            else:
                sizing_mult = 0.5
        else:
            sizing_mult = 1.0
        risk_amount = self.balance * (self.risk_per_trade_pct / 100) * sizing_mult
        quantity = risk_amount / risk_per_unit

        pos = OpenPosition(
            symbol=symbol,
            signal_type=signal_type,
            side=side,
            entry_time=timestamp if isinstance(timestamp, datetime) else datetime.now(timezone.utc),
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            quantity=quantity,
            risk_amount=risk_amount,
            atr=atr_value,
        )
        self.open_positions[symbol] = pos
        
        # Persist to DB
        if self.db:
            import asyncio
            db_pos = {
                "symbol": pos.symbol,
                "side": pos.side,
                "signal_type": pos.signal_type,
                "entry_time": pos.entry_time.replace(tzinfo=None),
                "entry_price": pos.entry_price,
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
                "quantity": pos.quantity,
                "risk_amount": pos.risk_amount,
                "atr": pos.atr
            }
            _pending_db = asyncio.ensure_future(self.db.save_position(db_pos))
            _pending_db.add_done_callback(
                lambda f: logger.error(f"DB save_position failed: {f.exception()}") if f.exception() else None
            )

        return pos

    def _check_position(self, pos: OpenPosition, current_price: float,
                          current_time: Optional[datetime] = None) -> Optional[Dict]:
        """
        Check if an open position hit SL or TP.
        Returns a dict if closed, None if still open.
        """
        exit_reason: Optional[str] = None
        exit_price: Optional[float] = None

        if pos.side == "LONG":
            if current_price >= pos.take_profit:
                exit_reason = "TAKE_PROFIT"
                exit_price = pos.take_profit
            elif current_price <= pos.stop_loss:
                exit_reason = "STOP_LOSS"
                exit_price = pos.stop_loss
        else:  # SHORT
            if current_price <= pos.take_profit:
                exit_reason = "TAKE_PROFIT"
                exit_price = pos.take_profit
            elif current_price >= pos.stop_loss:
                exit_reason = "STOP_LOSS"
                exit_price = pos.stop_loss

        if exit_reason is None or exit_price is None:
            return None

        # At this point mypy can narrow exit_reason/exit_price to str/float
        ep: float = exit_price
        er: str = exit_reason

        # Calculate PnL
        if pos.side == "LONG":
            profit = (ep - pos.entry_price) * pos.quantity
            profit_pct = (ep - pos.entry_price) / pos.entry_price
        else:
            profit = (pos.entry_price - ep) * pos.quantity
            profit_pct = (pos.entry_price - ep) / pos.entry_price

        rr = abs(ep - pos.entry_price) / abs(pos.entry_price - pos.stop_loss) \
            if abs(pos.entry_price - pos.stop_loss) > 0 else 0

        result = "WIN" if profit > 0 else ("LOSS" if profit < 0 else "BREAK_EVEN")

        # Update balance and daily P&L
        self.balance += profit
        self._daily_pnl += profit
        if self.balance > self._peak_balance:
            self._peak_balance = self.balance

        # Record stop-loss for cooldown tracking (prevents immediate same-side re-entry)
        if er == "STOP_LOSS":
            self._last_sl[pos.symbol] = {"time": current_time or datetime.now(timezone.utc), "side": pos.side}

        now = current_time if current_time is not None else datetime.now(timezone.utc)

        trade = ClosedTrade(
            symbol=pos.symbol,
            signal_type=pos.signal_type,
            side=pos.side,
            entry_time=pos.entry_time,
            exit_time=now,
            entry_price=pos.entry_price,
            exit_price=ep,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            quantity=pos.quantity,
            profit=profit,
            profit_pct=profit_pct,
            rr=round(rr, 2),
            result=result,
            exit_reason=er,
        )
        self.closed_trades.append(trade)
        
        # Persist to DB
        if self.db:
            import asyncio
            db_trade = {
                "symbol": trade.symbol,
                "signal_type": trade.signal_type,
                "side": trade.side,
                "entry_time": trade.entry_time.replace(tzinfo=None),
                "exit_time": trade.exit_time.replace(tzinfo=None),
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "stop_loss": trade.stop_loss,
                "take_profit": trade.take_profit,
                "quantity": trade.quantity,
                "profit": trade.profit,
                "profit_pct": trade.profit_pct,
                "rr": trade.rr,
                "result": trade.result,
                "exit_reason": trade.exit_reason
            }
            _pending_save = asyncio.ensure_future(self.db.save_trade(db_trade))
            _pending_save.add_done_callback(
                lambda f: logger.error(f"DB save_trade failed: {f.exception()}") if f.exception() else None
            )
            _pending_rm = asyncio.ensure_future(self.db.remove_position(pos.symbol))
            _pending_rm.add_done_callback(
                lambda f: logger.error(f"DB remove_position failed: {f.exception()}") if f.exception() else None
            )

        # Remove from open positions
        del self.open_positions[pos.symbol]

        logger.info(
            f"Demo closed {pos.side} {pos.symbol}: {result} "
            f"({exit_reason}) Profit=${profit:.2f} RR={trade.rr}"
        )

        return {
            "symbol": pos.symbol,
            "side": pos.side,
            "result": result,
            "exit_reason": exit_reason,
            "profit": round(profit, 2),
            "rr": trade.rr,
        }

    def _compute_equity(self, current_prices: Dict[str, float]) -> float:
        """Compute equity = balance + unrealized PnL of open positions."""
        unrealized = 0.0
        for pos in self.open_positions.values():
            price = current_prices.get(pos.symbol)
            if price is None:
                continue
            if pos.side == "LONG":
                unrealized += (price - pos.entry_price) * pos.quantity
            else:
                unrealized += (pos.entry_price - price) * pos.quantity
        return self.balance + unrealized
