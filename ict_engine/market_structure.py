import polars as pl
from typing import Optional, List, Dict
from datetime import datetime

class MarketStructure:
    def __init__(self, n: int = 3):
        self.n = n

    def detect_swings(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Detect Swing Highs and Swing Lows using N candles on each side.
        A swing high exists when Current High > Highest High of previous N and next N.
        """
        # Ensure we have enough data
        if len(df) < 2 * self.n + 1:
            return df.with_columns([
                pl.lit(None).alias("swing_high"),
                pl.lit(None).alias("swing_low")
            ])

        # Swing High Detection
        # shifted_max_prev = df['high'].shift(1).rolling_max(window_size=self.n)
        # shifted_max_next = df['high'].shift(-self.n).rolling_max(window_size=self.n)
        
        # Using polars rolling operations
        highs = df['high']
        lows = df['low']
        
        is_swing_high = (
            (highs == highs.rolling_max(window_size=2*self.n + 1, center=True)) &
            (highs.is_not_null())
        )
        
        is_swing_low = (
            (lows == lows.rolling_min(window_size=2*self.n + 1, center=True)) &
            (lows.is_not_null())
        )

        return df.with_columns([
            pl.when(is_swing_high).then(df['high']).otherwise(None).alias("swing_high"),
            pl.when(is_swing_low).then(df['low']).otherwise(None).alias("swing_low")
        ])

    def detect_bos_mss(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Detect Break of Structure (BOS) and Market Structure Shift (MSS).
        Bullish BOS: Close breaks above previous confirmed swing high.
        Bullish MSS: Previous swing low taken, then price closes above recent swing high.
        """
        if "swing_high" not in df.columns:
            df = self.detect_swings(df)

        # To track confirmed swings for BOS
        # We fill forward the last confirmed swing to compare with current close
        df = df.with_columns([
            pl.col("swing_high").forward_fill().alias("last_swing_high"),
            pl.col("swing_low").forward_fill().alias("last_swing_low")
        ])

        # Bullish BOS: Close > previous confirmed swing high
        is_bullish_bos = (pl.col("close") > pl.col("last_swing_high").shift(1)) & pl.col("last_swing_high").shift(1).is_not_null()
        # Bearish BOS: Close < previous confirmed swing low
        is_bearish_bos = (pl.col("close") < pl.col("last_swing_low").shift(1)) & pl.col("last_swing_low").shift(1).is_not_null()

        # MSS logic: Liquidity sweep (low taken) then break high
        # For simplicity, we track if the current candle is the *first* break after a sweep
        # Real implementation would track state, here we provide the indicators
        
        return df.with_columns([
            pl.when(is_bullish_bos).then(pl.lit("BULLISH")).when(is_bearish_bos).then(pl.lit("BEARISH")).otherwise(None).alias("bos"),
            # MSS is often a BOS that changes trend bias, for now we mark significant breaks
            pl.when(is_bullish_bos & (pl.col("close") > pl.col("last_swing_high").shift(2))).then(pl.lit("BULLISH_MSS")).otherwise(None).alias("mss")
        ])
