import abc
import asyncio
from typing import List, Dict
import polars as pl
from loguru import logger

class BaseCollector(abc.ABC):
    def __init__(self, symbols: List[str], timeframes: List[str]):
        self.symbols = symbols
        self.timeframes = timeframes
        self.is_running = False

    @abc.abstractmethod
    async def start(self):
        pass

    @abc.abstractmethod
    async def stop(self):
        pass

    @abc.abstractmethod
    async def fetch_historical(self, symbol: str, timeframe: str, limit: int = 1000) -> pl.DataFrame:
        pass

class MockCollector(BaseCollector):
    async def start(self):
        self.is_running = True
        logger.info("Mock Collector started.")
        while self.is_running:
            # Simulate real-time data
            await asyncio.sleep(60)
            logger.debug("Generating mock tick.")

    async def stop(self):
        self.is_running = False
        logger.info("Mock Collector stopped.")

    async def fetch_historical(self, symbol: str, timeframe: str, limit: int = 1000) -> pl.DataFrame:
        # Generate dummy data for testing
        import numpy as np
        import pandas as pd
        from datetime import datetime, timedelta
        
        dates = [datetime.now() - timedelta(minutes=i) for i in range(limit)]
        data = {
            "timestamp": sorted(dates),
            "open": np.random.uniform(1.0, 1.1, limit),
            "high": np.random.uniform(1.1, 1.2, limit),
            "low": np.random.uniform(0.9, 1.0, limit),
            "close": np.random.uniform(1.0, 1.1, limit),
            "volume": np.random.uniform(100, 1000, limit)
        }
        return pl.from_pandas(pd.DataFrame(data))
