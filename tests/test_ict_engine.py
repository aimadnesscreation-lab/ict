import pytest
import polars as pl
from datetime import datetime, timedelta
from ict_engine.market_structure import MarketStructure
from ict_engine.fvg import FVGDetector

@pytest.fixture
def mock_candles():
    data = {
        "timestamp": [datetime.now() - timedelta(minutes=i) for i in range(20)][::-1],
        "open":  [1.0, 1.1, 1.2, 1.1, 1.0, 0.9, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.4, 1.3, 1.2, 1.1, 1.0, 0.9],
        "high":  [1.05, 1.15, 1.25, 1.15, 1.05, 0.95, 0.85, 0.95, 1.05, 1.15, 1.25, 1.35, 1.45, 1.55, 1.45, 1.35, 1.25, 1.15, 1.05, 0.95],
        "low":   [0.95, 1.05, 1.15, 1.05, 0.95, 0.85, 0.75, 0.85, 0.95, 1.05, 1.15, 1.25, 1.35, 1.45, 1.35, 1.25, 1.15, 1.05, 0.95, 0.85],
        "close": [1.0, 1.1, 1.2, 1.1, 1.0, 0.9, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.4, 1.3, 1.2, 1.1, 1.0, 0.9],
        "volume": [100] * 20
    }
    return pl.DataFrame(data)

def test_swing_detection(mock_candles):
    ms = MarketStructure(n=2)
    df = ms.detect_swings(mock_candles)
    assert "swing_high" in df.columns
    assert "swing_low" in df.columns
    # With n=2, index 2 (1.25 high) should be a swing high if neighbors are lower
    # Index 2: high=1.25. Neighbors: 1.05, 1.15, 1.15, 1.05. Yes.
    assert df["swing_high"][2] == 1.25

def test_fvg_detection():
    data = {
        "high": [1.0, 1.1, 1.5],
        "low":  [0.9, 1.0, 1.4],
        "close": [0.95, 1.05, 1.45],
        "open": [0.92, 1.02, 1.42]
    }
    df = pl.DataFrame(data)
    detector = FVGDetector()
    df = detector.detect_fvgs(df)
    # Candle 0 high = 1.0
    # Candle 2 low = 1.4
    # 1.4 > 1.0 -> Bullish FVG at index 2
    assert df["fvg_type"][2] == "BULLISH"
    assert df["fvg_top"][2] == 1.4
    assert df["fvg_bottom"][2] == 1.0
