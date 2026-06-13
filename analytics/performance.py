import pandas as pd
import numpy as np
from typing import List, Dict

class PerformanceAnalytics:
    @staticmethod
    def calculate_metrics(trades: List[Dict]) -> Dict:
        """
        Calculate key performance metrics from a list of trades.
        """
        if not trades:
            return {}

        df = pd.DataFrame(trades)
        
        # Calculate returns
        df['return'] = df['profit'] / df['entry_price']
        
        win_rate = len(df[df['profit'] > 0]) / len(df)
        total_pnl = df['profit'].sum()
        
        # Profit Factor
        gross_profits = df[df['profit'] > 0]['profit'].sum()
        gross_losses = abs(df[df['profit'] <= 0]['profit'].sum())
        profit_factor = gross_profits / gross_losses if gross_losses != 0 else float('inf')
        
        # Equity Curve & Max Drawdown
        df['cumulative_profit'] = df['profit'].cumsum()
        df['equity'] = 10000 + df['cumulative_profit'] # Assuming 10k start
        df['peak'] = df['equity'].cummax()
        df['drawdown'] = (df['peak'] - df['equity']) / df['peak']
        max_drawdown = df['drawdown'].max()
        
        # Sharpe Ratio (Simplified assuming zero risk-free rate)
        returns = df['return']
        sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() != 0 else 0

        return {
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe,
            "total_trades": len(df)
        }
