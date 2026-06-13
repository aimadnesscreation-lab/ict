import polars as pl
from typing import List, Dict, Optional

class LiquidityDetector:
    """
    Objective liquidity detection based on mathematical rules.
    References: ict.md — Liquidity Module
    """

    def __init__(self, atr_threshold: float = 0.10):
        self.atr_threshold = atr_threshold
        self.atr_series: Optional[pl.Series] = None

    def _ensure_atr(self, df: pl.DataFrame) -> pl.Series:
        """Calculate ATR if not already present and cache it."""
        if "atr" not in df.columns:
            from .utils import calculate_atr
            self.atr_series = calculate_atr(df)
        else:
            self.atr_series = df["atr"]
        return self.atr_series

    def detect_equal_highs(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Detect Equal Highs (EQH).
        Two highs are equal when abs(high1 - high2) <= ATR * atr_threshold.
        """
        atr = self._ensure_atr(df)
        threshold = atr * self.atr_threshold

        prev_high = df["high"].shift(1)
        is_equal = (df["high"] - prev_high).abs() <= threshold

        return df.with_columns([
            pl.when(is_equal).then(df["high"]).otherwise(None).alias("eqh"),
        ])

    def detect_equal_lows(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Detect Equal Lows (EQL).
        Two lows are equal when abs(low1 - low2) <= ATR * atr_threshold.
        """
        atr = self._ensure_atr(df)
        threshold = atr * self.atr_threshold

        prev_low = df["low"].shift(1)
        is_equal = (df["low"] - prev_low).abs() <= threshold

        return df.with_columns([
            pl.when(is_equal).then(df["low"]).otherwise(None).alias("eql"),
        ])

    def detect_previous_day_levels(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Compute Previous Day High (PDH) and Previous Day Low (PDL)
        by grouping candles by trading date.

        Adds columns: pdh, pdl, pwh, pwl
        """
        if "timestamp" not in df.columns:
            return df.with_columns([
                pl.lit(None).alias("pdh"),
                pl.lit(None).alias("pdl"),
            ])

        # Extract date from timestamp (coerce to datetime if it's a string)
        ts_col = df["timestamp"]
        if ts_col.dtype == pl.Utf8:
            ts_col = ts_col.str.to_datetime()
        df = df.with_columns([
            ts_col.dt.date().alias("trading_date"),
        ])

        # Compute daily OHLC
        daily = df.group_by("trading_date").agg([
            pl.col("high").max().alias("d_high"),
            pl.col("low").min().alias("d_low"),
        ]).sort("trading_date")

        # Shift by 1 to get *previous* day levels
        daily = daily.with_columns([
            daily["d_high"].shift(1).alias("pdh_val"),
            daily["d_low"].shift(1).alias("pdl_val"),
        ])

        # Join back to main dataframe
        df = df.join(
            daily.select(["trading_date", "pdh_val", "pdl_val"]),
            on="trading_date",
            how="left"
        )

        return df.with_columns([
            pl.col("pdh_val").alias("pdh"),
            pl.col("pdl_val").alias("pdl"),
        ]).drop(["trading_date", "pdh_val", "pdl_val"])

    def detect_liquidity_sweeps(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Detect Liquidity Sweeps.
        
        Bullish Sweep:
          1. Price breaks below a liquidity level (previous swing low or EQL).
          2. Price closes back above that level.
        
        Bearish Sweep:
          1. Price breaks above a liquidity level (previous swing high or EQH).
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
        df = self.detect_equal_highs(df)
        df = self.detect_equal_lows(df)
        df = self.detect_previous_day_levels(df)
        if "swing_low" in df.columns:
            df = self.detect_liquidity_sweeps(df)
        return df
