from loguru import logger
from typing import Optional

class RiskManager:
    def __init__(self, 
                 max_risk_per_trade_pct: float = 1.0, 
                 max_daily_loss_pct: float = 3.0,
                 max_open_positions: int = 3):
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_open_positions = max_open_positions
        
        self.current_daily_loss = 0.0
        self.open_positions_count = 0

    def calculate_position_size(self, 
                                account_balance: float, 
                                entry_price: float, 
                                stop_loss: float) -> Optional[float]:
        """
        Calculate position size based on fixed percentage risk.
        """
        if self.open_positions_count >= self.max_open_positions:
            logger.warning("Max open positions reached. Skipping trade.")
            return None

        if self.current_daily_loss >= (account_balance * self.max_daily_loss_pct / 100):
            logger.warning("Max daily loss reached. Skipping trade.")
            return None

        risk_amount = account_balance * (self.max_risk_per_trade_pct / 100)
        risk_per_unit = abs(entry_price - stop_loss)
        
        if risk_per_unit == 0:
            return None
            
        position_size = risk_amount / risk_per_unit
        return position_size

    def update_state(self, daily_pnl: float, open_positions: int):
        self.current_daily_loss = daily_pnl
        self.open_positions_count = open_positions
