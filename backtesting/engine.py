import polars as pl
from typing import List, Dict, Optional
from loguru import logger

class BacktestEngine:
    def __init__(self, initial_capital: float = 10000.0, rr_target: float = 2.0, rr_stop: float = 1.0):
        self.capital = initial_capital
        self.rr_target = rr_target
        self.rr_stop = rr_stop
        self.trades: List[Dict] = []

    def run(self, df: pl.DataFrame, signals: List[Dict]) -> Dict:
        """
        Run backtest on a dataframe given a list of signals.
        """
        self.trades = []
        for signal in signals:
            self._process_signal(df, signal)
        return self.get_report()

    def _process_signal(self, df: pl.DataFrame, signal: Dict):
        """
        Simulate trade by looking ahead in the candle stream.
        Entry, SL, and TP prices are derived from signal attributes.
        """
        signal_time = signal.get("timestamp")
        entry_price = signal.get("price", 0)
        signal_type = signal.get("signal_type", "NEUTRAL")

        if entry_price == 0 or signal_type == "NEUTRAL":
            return

        is_long = "BUY" in signal_type

        # Set stop-loss and take-profit based on a fixed ATR-based range
        # If ATR isn't available, fall back to a 1% stop
        atr_value = signal.get("atr", entry_price * 0.01)
        stop_distance = atr_value * self.rr_stop
        target_distance = atr_value * self.rr_target

        if is_long:
            stop_price = entry_price - stop_distance
            target_price = entry_price + target_distance
        else:
            stop_price = entry_price + stop_distance
            target_price = entry_price - target_distance

        # Find the signal's position in the dataframe
        signal_idx = None
        if signal_time is not None:
            timestamps = df["timestamp"].to_list()
            for i, ts in enumerate(timestamps):
                if ts >= signal_time:
                    signal_idx = i
                    break

        if signal_idx is None:
            signal_idx = 0

        # Iterate through future candles to see if TP or SL is hit first
        exit_idx = None
        exit_price = None
        max_bars = 100  # prevent infinite look-ahead

        for i in range(signal_idx + 1, min(signal_idx + max_bars + 1, len(df))):
            candle = df.row(i, named=True)
            candle_high = candle["high"]
            candle_low = candle["low"]

            if is_long:
                # Hit target?
                if candle_high >= target_price:
                    exit_idx = i
                    exit_price = target_price
                    break
                # Hit stop?
                if candle_low <= stop_price:
                    exit_idx = i
                    exit_price = stop_price
                    break
            else:
                # Hit target?
                if candle_low <= target_price:
                    exit_idx = i
                    exit_price = target_price
                    break
                # Hit stop?
                if candle_high >= stop_price:
                    exit_idx = i
                    exit_price = stop_price
                    break

        if exit_price is None:
            # No TP/SL hit within max_bars — close at last candle close
            exit_idx = min(signal_idx + max_bars, len(df) - 1)
            exit_price = df["close"][exit_idx]

        # Calculate profit
        if is_long:
            profit = exit_price - entry_price
        else:
            profit = entry_price - exit_price

        risk = abs(entry_price - stop_price)
        rr_ratio = profit / risk if risk > 0 else 0
        result = "WIN" if profit > 0 else ("LOSS" if profit < 0 else "BREAK_EVEN")

        exit_time = df["timestamp"][exit_idx]

        trade = {
            "signal_type": signal_type,
            "entry_time": signal_time if signal_time else exit_time,
            "exit_time": exit_time,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "profit": round(profit, 6),
            "rr": round(rr_ratio, 2),
            "result": result,
        }
        self.trades.append(trade)

    def get_report(self) -> Dict:
        """
        Compute backtest summary statistics.
        """
        if not self.trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "total_profit": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "capital_remaining": self.capital
            }

        wins = [t for t in self.trades if t['result'] == 'WIN']
        losses = [t for t in self.trades if t['result'] == 'LOSS']
        total_profit = sum(t['profit'] for t in self.trades)

        win_rate = len(wins) / len(self.trades) if self.trades else 0

        gross_profits = sum(t['profit'] for t in wins)
        gross_losses = abs(sum(t['profit'] for t in losses))
        profit_factor = gross_profits / gross_losses if gross_losses != 0 else (float('inf') if gross_profits > 0 else 0)

        # Max drawdown on the equity curve
        equity = self.capital
        peak = equity
        max_drawdown = 0.0
        for t in self.trades:
            equity += t['profit']
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd

        return {
            "total_trades": len(self.trades),
            "win_rate": round(win_rate, 4),
            "total_profit": round(total_profit, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown": round(max_drawdown, 4),
            "capital_remaining": round(self.capital + total_profit, 2),
            "avg_rr": round(
                sum(t['rr'] for t in self.trades) / len(self.trades), 2
            ) if self.trades else 0,
            "avg_profit": round(total_profit / len(self.trades), 6) if self.trades else 0,
        }
