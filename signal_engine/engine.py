import polars as pl


def determine_bias_from_swings(df: pl.DataFrame) -> str:
    """
    Determine local bias based on the most recent confirmed swing levels.
    """
    if "swing_high" not in df.columns or "swing_low" not in df.columns:
        return "neutral"

    recent_highs = df["swing_high"].drop_nulls()
    recent_lows = df["swing_low"].drop_nulls()

    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return "neutral"

    # Higher High + Higher Low = Bullish
    if recent_highs[-1] > recent_highs[-2] and recent_lows[-1] > recent_lows[-2]:
        return "bullish"
    # Lower Low + Lower High = Bearish
    if recent_highs[-1] < recent_highs[-2] and recent_lows[-1] < recent_lows[-2]:
        return "bearish"

    return "neutral"


def determine_bias_from_ema(df: pl.DataFrame, period: int = 50) -> str:
    """
    Trend identification using EMA.
    """
    if len(df) < period:
        return "neutral"

    ema = df["close"].ewm_mean(span=period, adjust=False)
    last_close = df["close"][-1]
    last_ema = ema[-1]

    if last_close > last_ema:
        return "bullish"
    elif last_close < last_ema:
        return "bearish"
    return "neutral"
