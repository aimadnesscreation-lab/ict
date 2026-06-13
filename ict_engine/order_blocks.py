import polars as pl
from typing import List, Dict, Optional
from .utils import calculate_atr

class OrderBlockDetector:
    def __init__(self, atr_multiplier: float = 2.0, expansion_window: int = 3):
        self.atr_multiplier = atr_multiplier
        self.expansion_window = expansion_window

    def detect_order_blocks(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Detect Order Blocks.
        Bullish OB: Last bearish candle before bullish impulse (2x ATR).
        Bearish OB: Last bullish candle before bearish impulse (2x ATR).
        """
        if len(df) < self.expansion_window + 1:
            return df.with_columns([
                pl.lit(None).alias("ob_type"),
                pl.lit(None).alias("ob_high"),
                pl.lit(None).alias("ob_low")
            ])

        if "atr" not in df.columns:
            df = df.with_columns(calculate_atr(df).alias("atr"))

        # Impulse Move Detection
        # Shift(-1) to look ahead for expansion
        # Total move over next X candles
        future_close = df['close'].shift(-self.expansion_window)
        current_close = df['close']
        
        move_size = (future_close - current_close).abs()
        is_expansion = move_size > (df['atr'] * self.atr_multiplier)
        
        is_bullish_expansion = (future_close > current_close) & is_expansion
        is_bearish_expansion = (future_close < current_close) & is_expansion

        # Candle types
        is_bearish_candle = df['close'] < df['open']
        is_bullish_candle = df['close'] > df['open']

        # Bullish OB is the last bearish candle before bullish expansion
        is_bullish_ob = is_bullish_expansion & is_bearish_candle
        # Bearish OB is the last bullish candle before bearish expansion
        is_bearish_ob = is_bearish_expansion & is_bullish_candle

        return df.with_columns([
            pl.when(is_bullish_ob).then(pl.lit("BULLISH"))
              .when(is_bearish_ob).then(pl.lit("BEARISH"))
              .otherwise(None).alias("ob_type"),
            
            pl.when(is_bullish_ob | is_bearish_ob).then(df['high']).otherwise(None).alias("ob_high"),
            pl.when(is_bullish_ob | is_bearish_ob).then(df['low']).otherwise(None).alias("ob_low")
        ])
