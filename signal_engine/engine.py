import polars as pl
from typing import Dict, List, Optional
from ict_engine.market_structure import MarketStructure
from ict_engine.fvg import FVGDetector
from ict_engine.order_blocks import OrderBlockDetector

class SignalEngine:
    def __init__(self, weights: Optional[Dict[str, int]] = None):
        # Default weights from full.md
        self.weights = weights or {
            "bias": 20,
            "mss": 20,
            "liquidity_sweep": 20,
            "fvg": 15,
            "order_block": 15,
            "news": 10
        }

    def generate_signal(self, 
                        df: pl.DataFrame, 
                        mss: bool = False, 
                        sweep: bool = False,
                        news_sentiment: float = 0.0) -> Dict:
        """
        Generate a signal based on weighted scoring.
        """
        score = 0
        
        # 1. Bias (Simplified for now: trend based on last 2 swings)
        # score += self.weights["bias"] if trend == "bullish" else 0
        
        # 2. MSS
        if mss:
            score += self.weights["mss"]
            
        # 3. Liquidity Sweep
        if sweep:
            score += self.weights["liquidity_sweep"]
            
        # 4. FVG (Is price currently in a FVG?)
        # 5. Order Block (Is price currently in an OB?)
        
        # Check current price against detections
        current_candle = df.tail(1).to_dicts()[0]
        current_price = current_candle["close"]
        
        # Simplified FVG/OB check
        has_fvg = df["fvg_type"].tail(5).is_not_null().any()
        if has_fvg:
            score += self.weights["fvg"]
            
        has_ob = df["ob_type"].tail(5).is_not_null().any()
        if has_ob:
            score += self.weights["order_block"]
            
        # 6. News
        if news_sentiment > 0.5:
            score += self.weights["news"]
            
        # Categorize
        signal_type = "NEUTRAL"
        if score >= 80:
            signal_type = "STRONG_BUY"
        elif score >= 60:
            signal_type = "BUY"
        elif score <= 20:
            signal_type = "STRONG_SELL"
        elif score <= 40:
            signal_type = "SELL"
            
        return {
            "score": score,
            "signal_type": signal_type,
            "timestamp": current_candle["timestamp"],
            "price": current_price,
            "details": {
                "mss": mss,
                "sweep": sweep,
                "fvg": has_fvg,
                "ob": has_ob,
                "news_sentiment": news_sentiment
            }
        }
