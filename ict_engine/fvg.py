import polars as pl


class FVGDetector:
    def detect_fvgs(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Detect Fair Value Gaps (FVG).
        Bullish FVG: Candle[i-2].high < Candle[i].low
        Bearish FVG: Candle[i-2].low > Candle[i].high
        """
        if len(df) < 3:
            return df.with_columns([
                pl.lit(None).alias("fvg_type"),
                pl.lit(None).alias("fvg_top"),
                pl.lit(None).alias("fvg_bottom")
            ])

        high_minus_2 = df['high'].shift(2)
        low_minus_2 = df['low'].shift(2)

        current_low = df['low']
        current_high = df['high']

        is_bullish_fvg = current_low > high_minus_2
        is_bearish_fvg = current_high < low_minus_2

        return df.with_columns([
            pl.when(is_bullish_fvg).then(pl.lit("BULLISH"))
              .when(is_bearish_fvg).then(pl.lit("BEARISH"))
              .otherwise(None).alias("fvg_type"),

            pl.when(is_bullish_fvg).then(current_low)
              .when(is_bearish_fvg).then(low_minus_2)
              .otherwise(None).alias("fvg_top"),

            pl.when(is_bullish_fvg).then(high_minus_2)
              .when(is_bearish_fvg).then(current_high)
              .otherwise(None).alias("fvg_bottom")
        ])
