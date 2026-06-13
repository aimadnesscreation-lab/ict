import polars as pl

def calculate_atr(df: pl.DataFrame, period: int = 14) -> pl.Series:
    """
    Calculate Average True Range (ATR).
    """
    prev_close = df['close'].shift(1)
    
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - prev_close).abs()
    tr3 = (df['low'] - prev_close).abs()
    
    # tr = pl.max_horizontal(tr1, tr2, tr3) # polars >= 0.19.12
    # For older polars or more explicit:
    tr = pl.concat_list([tr1, tr2, tr3]).list.max()
    
    return tr.rolling_mean(window_size=period)

def calculate_smma(series: pl.Series, period: int) -> pl.Series:
    """
    Smoothed Moving Average.
    """
    return series.ewm_mean(span=2 * period - 1, adjust=False)
