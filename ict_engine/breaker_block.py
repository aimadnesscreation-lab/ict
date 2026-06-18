"""
ICT Breaker Block Module.

References: ict.md — Breaker Block Module

A breaker block forms when:
  1. An order block is identified (OB)
  2. Price breaks through the OB (invalidates it)
  3. Price then retests the broken level
  4. The OB level now acts as the opposite role (resistance → support or vice versa)

Breaker blocks signal a shift in market structure and often precede
strong continuation moves.
"""

import polars as pl


class BreakerBlockDetector:
    """Detect breaker blocks from order block failures and retests."""

    def __init__(self, retest_window: int = 10):
        self.retest_window = retest_window  # candles to look for retest after break

    def detect_breaker_blocks(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Detect breaker blocks by tracking order block validity.

        Bullish Breaker:
          1. A bearish OB was detected (resistance level)
          2. Price breaks above the OB high
          3. Price retests the OB high from above → now acts as support

        Bearish Breaker:
          1. A bullish OB was detected (support level)
          2. Price breaks below the OB low
          3. Price retests the OB low from below → now acts as resistance
        """
        if "ob_type" not in df.columns or "ob_high" not in df.columns or "ob_low" not in df.columns:
            return df.with_columns([
                pl.lit(None).alias("breaker_type"),
                pl.lit(None).alias("breaker_price"),
            ])

        # We'll use Polars expressions for vectorized detection

        # Bullish breaker: bearish OB (resistance) broken to the upside, then retested
        # A bearish OB has ob_type="BEARISH", its high is the resistance level
        ob_is_bearish = df["ob_type"] == "BEARISH"
        ob_bearish_high = df["ob_high"]

        # Check if price breaks above the bearish OB high (within retest_window candles)
        future_high = df["high"].shift(-1).rolling_max(window_size=self.retest_window)
        broke_above = (future_high > ob_bearish_high) & ob_is_bearish

        # Retest: price comes back down to touch the broken level from above
        future_low = df["low"].shift(-1).rolling_min(window_size=self.retest_window)
        retested_from_above = (future_low <= ob_bearish_high) & broke_above

        # Bearish breaker: bullish OB (support) broken to the downside, then retested
        ob_is_bullish = df["ob_type"] == "BULLISH"
        ob_bullish_low = df["ob_low"]

        # Check if price breaks below the bullish OB low
        future_low2 = df["low"].shift(-1).rolling_min(window_size=self.retest_window)
        broke_below = (future_low2 < ob_bullish_low) & ob_is_bullish

        # Retest: price comes back up to touch the broken level from below
        future_high2 = df["high"].shift(-1).rolling_max(window_size=self.retest_window)
        retested_from_below = (future_high2 >= ob_bullish_low) & broke_below

        return df.with_columns([
            pl.when(retested_from_above).then(pl.lit("BULLISH_BREAKER"))
              .when(retested_from_below).then(pl.lit("BEARISH_BREAKER"))
              .otherwise(None).alias("breaker_type"),

            pl.when(retested_from_above).then(ob_bearish_high)
              .when(retested_from_below).then(ob_bullish_low)
              .otherwise(None).alias("breaker_price"),
        ])
