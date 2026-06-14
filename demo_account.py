"""
Demo Account — Stateful Forward Testing Engine.

Opens trades based on live signals, tracks open positions in memory,
checks SL/TP against current prices every cycle, and maintains
full trade history + performance metrics.

Rules:
  - 1% risk per trade (of current account balance)
  - 1:2 risk-reward (SL = 1× ATR, TP = 2× ATR)
  - Only trades signals with score ≥ 70 AND inside a kill zone (matches Discord alerts)
  - Long on BUY/STRONG_BUY, Short on SELL/STRONG_SELL
  - Max 1 open position per symbol (ignores weaker signals if already in)
  - Account starts at $10,000
"""

from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
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
    def __init__(self, initial_balance: float = 10_000.0, risk_per_trade_pct: float = 1.0,
                 max_daily_loss_pct: float = 3.0, max_open_positions: int = 3):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.equity = initial_balance
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_open_positions = max_open_positions
        self.open_positions: Dict[str, OpenPosition] = {}  # keyed by symbol
        self.closed_trades: List[ClosedTrade] = []
        self._peak_balance = initial_balance
        self._daily_pnl = 0.0

    # ── Public API ────────────────────────────────────────────────────

    def process_signals(self, signals: List[Dict], current_prices: Dict[str, float]) -> List[Dict]:
        """
        Main entry point — called every signal cycle.
        1. Check open positions against current prices → close any that hit SL/TP
        2. Open new positions for strong signals not already in a position

        Returns the list of trades that were closed this cycle (for logging).
        """
        freshly_closed: List[Dict] = []

        # Step 1: Check existing positions
        for symbol in list(self.open_positions.keys()):
            pos = self.open_positions[symbol]
            current_price = current_prices.get(symbol)
            if current_price is None:
                continue

            trade = self._check_position(pos, current_price)
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
            if score < 70 or not signal.get("in_kill_zone", False):
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
            else:
                continue

            # Use ATR (fallback to 1% of price if unavailable)
            atr_value = atr if atr > 0 else price * 0.01
            if atr_value <= 0:
                continue

            pos = self._open_trade(symbol, signal_type, side, price, atr_value, timestamp)
            if pos:
                logger.info(
                    f"Demo opened {side} {symbol} @ {price:.2f} "
                    f"SL={pos.stop_loss:.2f} TP={pos.take_profit:.2f} "
                    f"Qty={pos.quantity:.4f} Risk=${pos.risk_amount:.2f}"
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
        """Return open positions in API-friendly format."""
        return [
            {
                "symbol": pos.symbol,
                "side": pos.side,
                "signal_type": pos.signal_type,
                "entry_time": pos.entry_time.isoformat() if hasattr(pos.entry_time, "isoformat") else str(pos.entry_time),
                "entry_price": round(pos.entry_price, 2),
                "current_price": 0.0,  # caller should fill this
                "stop_loss": round(pos.stop_loss, 2),
                "take_profit": round(pos.take_profit, 2),
                "quantity": round(pos.quantity, 6),
                "risk_amount": round(pos.risk_amount, 2),
                "unrealized_pnl": 0.0,  # caller should fill
            }
            for pos in self.open_positions.values()
        ]

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
                    price: float, atr_value: float, timestamp) -> Optional[OpenPosition]:
        """Open a new position with 1% risk, 1:2 RR using ATR."""
        if side == "LONG":
            stop_loss = price - atr_value
            take_profit = price + (2 * atr_value)
        else:
            stop_loss = price + atr_value
            take_profit = price - (2 * atr_value)

        risk_per_unit = abs(price - stop_loss)
        if risk_per_unit <= 0:
            return None

        # Risk 1% of current balance
        risk_amount = self.balance * (self.risk_per_trade_pct / 100)
        quantity = risk_amount / risk_per_unit

        pos = OpenPosition(
            symbol=symbol,
            signal_type=signal_type,
            side=side,
            entry_time=timestamp if isinstance(timestamp, datetime) else datetime.utcnow(),
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            quantity=quantity,
            risk_amount=risk_amount,
            atr=atr_value,
        )
        self.open_positions[symbol] = pos
        return pos

    def _check_position(self, pos: OpenPosition, current_price: float) -> Optional[Dict]:
        """
        Check if an open position hit SL or TP.
        Returns a dict if closed, None if still open.
        """
        exit_reason = None
        exit_price = None

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

        if exit_reason is None:
            return None

        # Calculate PnL
        if pos.side == "LONG":
            profit = (exit_price - pos.entry_price) * pos.quantity
            profit_pct = (exit_price - pos.entry_price) / pos.entry_price
        else:
            profit = (pos.entry_price - exit_price) * pos.quantity
            profit_pct = (pos.entry_price - exit_price) / pos.entry_price

        rr = abs(exit_price - pos.entry_price) / abs(pos.entry_price - pos.stop_loss) \
            if abs(pos.entry_price - pos.stop_loss) > 0 else 0

        result = "WIN" if profit > 0 else ("LOSS" if profit < 0 else "BREAK_EVEN")

        # Update balance and daily P&L
        self.balance += profit
        self._daily_pnl += profit
        if self.balance > self._peak_balance:
            self._peak_balance = self.balance

        trade = ClosedTrade(
            symbol=pos.symbol,
            signal_type=pos.signal_type,
            side=pos.side,
            entry_time=pos.entry_time,
            exit_time=datetime.utcnow(),
            entry_price=pos.entry_price,
            exit_price=exit_price,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            quantity=pos.quantity,
            profit=profit,
            profit_pct=profit_pct,
            rr=round(rr, 2),
            result=result,
            exit_reason=exit_reason,
        )
        self.closed_trades.append(trade)

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
