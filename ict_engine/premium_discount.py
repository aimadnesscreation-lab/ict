"""
ICT Premium, Discount & OTE (Optimal Trade Entry) Module.

References: ict.md — Premium Discount Module, OTE Module

Premium/Discount:
  - Dealing Range = Recent Swing High – Recent Swing Low
  - Equilibrium = (High + Low) / 2
  - Premium: Price above equilibrium (expensive)
  - Discount: Price below equilibrium (cheap)

OTE Zones (Fibonacci retracements of the dealing range):
  - 62%  retracement
  - 70.5% retracement
  - 79%  retracement
"""

import polars as pl
from typing import Dict, Optional, Tuple


class PremiumDiscountDetector:
    """Detect premium/discount zones and calculate OTE levels."""

    def __init__(self, lookback: int = 288):
        # lookback bounds the dealing-range computation to a FIXED number of
        # recent bars. Without this, the range was derived from the last swing
        # over the *entire* input buffer, so a variable-length live buffer would
        # shift `equilibrium` and silently flip the discount/premium gate that
        # signals depend on. A fixed lookback keeps live == backtest.
        self.lookback = lookback
        self.last_swing_high: Optional[float] = None
        self.last_swing_low: Optional[float] = None

    def _get_range_high_low(self, df: pl.DataFrame) -> Tuple[Optional[float], Optional[float]]:
        """
        Determine the dealing range from the most recent swing points within a
        FIXED lookback window. Falls back to recent price range if swings are
        unavailable.
        """
        # Bound to a fixed recent window so the range is buffer-length-invariant.
        window = df.tail(self.lookback) if len(df) > self.lookback else df

        swing_high = None
        swing_low = None

        if "swing_high" in window.columns:
            recent_highs = window["swing_high"].drop_nulls()
            if len(recent_highs) > 0:
                swing_high = recent_highs[-1]

        if "swing_low" in window.columns:
            recent_lows = window["swing_low"].drop_nulls()
            if len(recent_lows) > 0:
                swing_low = recent_lows[-1]

        # Fallback to recent candle range
        if swing_high is None:
            swing_high = window["high"].tail(20).max()
        if swing_low is None:
            swing_low = window["low"].tail(20).min()

        return (swing_high, swing_low)

    def compute_zones(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Add premium/discount zone and OTE columns to the dataframe.
        """
        range_high, range_low = self._get_range_high_low(df)

        if range_high is None or range_low is None or range_high == range_low:
            return df.with_columns([
                pl.lit(None).alias("equilibrium"),
                pl.lit(None).alias("zone"),
                pl.lit(None).alias("ote_62"),
                pl.lit(None).alias("ote_705"),
                pl.lit(None).alias("ote_79"),
                pl.lit(None).alias("in_ote"),
                pl.lit(None).alias("in_discount"),
            ])

        dealing_range = range_high - range_low
        equilibrium = (range_high + range_low) / 2

        # OTE fib levels (retracement from the range)
        # For bullish: we retrace from low to high
        # For bearish: we retrace from high to low
        ote_62 = range_low + dealing_range * 0.62
        ote_705 = range_low + dealing_range * 0.705
        ote_79 = range_low + dealing_range * 0.79

        current_price = df["close"]

        # Zone: premium if above equilibrium, discount if below
        zone = pl.when(current_price >= equilibrium).then(pl.lit("premium")).otherwise(pl.lit("discount"))

        # In discount zone (below equilibrium)
        in_discount = current_price < equilibrium

        # In OTE zone: price between 62% and 79% retracement (from low)
        in_ote = (current_price >= ote_62) & (current_price <= ote_79)

        return df.with_columns([
            pl.lit(round(equilibrium, 8)).alias("equilibrium"),
            zone.alias("zone"),
            pl.lit(round(ote_62, 8)).alias("ote_62"),
            pl.lit(round(ote_705, 8)).alias("ote_705"),
            pl.lit(round(ote_79, 8)).alias("ote_79"),
            in_ote.alias("in_ote"),
            in_discount.alias("in_discount"),
        ])

    def get_score_contribution(self, df: pl.DataFrame, trend_bias: str) -> Dict[str, int]:
        """
        Calculate confluence score from premium/discount/OTE analysis.

        Returns dict with keys:
          - discount_score: +10 if in discount zone
          - ote_score: +10 if in OTE zone
          - total: sum of both
        """
        if "zone" not in df.columns:
            df = self.compute_zones(df)

        latest = df.tail(1).to_dicts()[0]
        score = {"discount_score": 0, "ote_score": 0}

        # Discount zone = +10 (price at a value area)
        in_discount = latest.get("in_discount", False)
        in_ote = latest.get("in_ote", False)

        # Score depends on alignment with trend bias
        if trend_bias == "bullish" and in_discount:
            score["discount_score"] = 10
        elif trend_bias == "bearish" and not in_discount:
            # Bearish trend prefers premium zone (selling high)
            score["discount_score"] = 10

        if in_ote:
            score["ote_score"] = 10

        score["total"] = score["discount_score"] + score["ote_score"]
        return score
