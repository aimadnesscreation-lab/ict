import httpx
import asyncio
import polars as pl
from typing import List, Optional
from datetime import datetime
from loguru import logger
from .collector import BaseCollector

class BinanceCollector(BaseCollector):
    def __init__(self, symbols: List[str], timeframes: List[str]):
        super().__init__(symbols, timeframes)
        self.base_url = "https://api.binance.com/api/v3"

    async def start(self):
        self.is_running = True
        logger.info(f"Binance Collector started for {self.symbols}")
        # In a real implementation, this would start the WebSocket streams
        while self.is_running:
            await asyncio.sleep(60)

    async def stop(self):
        self.is_running = False
        logger.info("Binance Collector stopped.")

    async def fetch_historical(self, symbol: str, timeframe: str, limit: int = 500) -> pl.DataFrame:
        """
        Fetch historical klines from Binance.
        """
        # Map timeframes to Binance format
        tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
        binance_tf = tf_map.get(timeframe, "1h")
        
        url = f"{self.base_url}/klines?symbol={symbol.upper()}&interval={binance_tf}&limit={limit}"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                
                # Binance Klines format:
                # [ [OpenTime, Open, High, Low, Close, Volume, CloseTime, ...], ... ]
                df_data = {
                    "timestamp": [datetime.fromtimestamp(x[0]/1000) for x in data],
                    "open": [float(x[1]) for x in data],
                    "high": [float(x[2]) for x in data],
                    "low": [float(x[3]) for x in data],
                    "close": [float(x[4]) for x in data],
                    "volume": [float(x[5]) for x in data]
                }
                return pl.DataFrame(df_data)
            except Exception as e:
                logger.error(f"Binance fetch failed for {symbol}: {e}")
                return pl.DataFrame()
