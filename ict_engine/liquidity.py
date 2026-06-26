import polars as pl
from typing import Optional

class LiquidityDetector:
    """
    Objective liquidity detection based on mathematical rules.
    References: ict.md — Liquidity Module
    """

    def __init__(self, atr_threshold: float = 0.10):
        self.atr_threshold = atr_threshold
        self.atr_series: Optional[pl.Series] = None

    def _ensure_atr(self, df: pl.DataFrame) -> pl.DataFrame:
        """Calculate ATR if not already present and add it to the DataFrame."""
        if "atr" not in df.columns:
            from .utils import calculate_atr
            df = df.with_columns(calculate_atr(df).alias("atr"))
        return df

    def detect_liquidity_sweeps(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Detect Liquidity Sweeps.
        
        Bullish Sweep:
          1. Price breaks below a liquidity level (previous swing low).
          2. Price closes back above that level.
        
        Bearish Sweep:
          1. Price breaks above a liquidity level (previous swing high).
          2. Price closes back below that level.
        """
        if "swing_low" not in df.columns or "swing_high" not in df.columns:
            return df.with_columns([
                pl.lit(None).alias("liquidity_sweep_type"),
                pl.lit(None).alias("liquidity_sweep_price"),
            ])

        # Forward-fill the last confirmed swing levels
        df = df.with_columns([
            pl.col("swing_low").forward_fill().alias("last_swing_low"),
            pl.col("swing_high").forward_fill().alias("last_swing_high"),
        ])

        shifted_low = df["last_swing_low"].shift(1)
        shifted_high = df["last_swing_high"].shift(1)

        # Bullish Sweep: low < last_swing_low (break), then close > last_swing_low (reclaim)
        broke_low = df["low"] < shifted_low
        reclaimed_low = df["close"] > shifted_low
        is_bullish_sweep = broke_low & reclaimed_low & shifted_low.is_not_null()

        # Bearish Sweep: high > last_swing_high (break), then close < last_swing_high (reclaim)
        broke_high = df["high"] > shifted_high
        reclaimed_high = df["close"] < shifted_high
        is_bearish_sweep = broke_high & reclaimed_high & shifted_high.is_not_null()

        return df.with_columns([
            pl.when(is_bullish_sweep).then(pl.lit("BULLISH"))
              .when(is_bearish_sweep).then(pl.lit("BEARISH"))
              .otherwise(None).alias("liquidity_sweep_type"),

            pl.when(is_bullish_sweep).then(shifted_low)
              .when(is_bearish_sweep).then(shifted_high)
              .otherwise(None).alias("liquidity_sweep_price"),
        ])

    def detect_all(self, df: pl.DataFrame) -> pl.DataFrame:
        """Run all liquidity detection methods and return enhanced dataframe."""
        if "swing_low" in df.columns:
            df = self.detect_liquidity_sweeps(df)
        return df
