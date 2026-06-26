import polars as pl

class MarketStructure:
    def __init__(self, n: int = 2):
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
