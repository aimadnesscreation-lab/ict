import asyncio
import time
import httpx
import polars as pl
from typing import List
from datetime import datetime
from loguru import logger
from .collector import BaseCollector


class CoinGeckoCollector(BaseCollector):
    """Fetch crypto OHLCV data from CoinGecko's free API.

    CoinGecko's OHLC endpoint returns candles at fixed granularities:
      - days=1  → ~5-minute candles (288 max)
      - days=7  → hourly candles (168 max)
      - days=30 → 4-hourly candles

    For 15m, we fetch 5m data (days=1) and resample every 3 candles.
    Volume is not included in CoinGecko's OHLC response, so it's set to 0.
    """

    SYMBOL_TO_ID = {
        "BTCUSDT": "bitcoin",
        "ETHUSDT": "ethereum",
    }

    def __init__(self, symbols: List[str], timeframes: List[str]):
        super().__init__(symbols, timeframes)
        self.base_url = "https://api.coingecko.com/api/v3"
        self._last_request_time = 0.0
        self._min_interval = 15.0  # minimum seconds between requests (free tier conservative: ~4 calls/min)

    async def start(self):
        self.is_running = True
        logger.info(f"CoinGecko Collector started for {self.symbols}")

    async def stop(self):
        self.is_running = False
        logger.info("CoinGecko Collector stopped.")

    async def _throttle(self):
        """Ensure minimum interval between API requests."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    async def fetch_historical(
        self, symbol: str, timeframe: str, limit: int = 500
    ) -> pl.DataFrame:
        """Fetch OHLC candles from CoinGecko.

        For 15m, fetches 5m data and resamples.
        Trims to requested limit from the tail (most recent).
        """
        coin_id = self.SYMBOL_TO_ID.get(symbol)
        if not coin_id:
            logger.error(f"Unknown symbol for CoinGecko: {symbol}")
            return pl.DataFrame()

        # Determine days parameter — controls candle granularity
        if timeframe in ("5m", "15m"):
            days = 1  # 5-minute candles
        elif timeframe == "1h":
            days = 7  # hourly candles
        else:
            logger.error(f"Unsupported timeframe for CoinGecko: {timeframe}")
            return pl.DataFrame()

        # Retry up to 2 times on rate-limit (429)
        max_retries = 2
        for attempt in range(1, max_retries + 1):
            await self._throttle()

            url = f"{self.base_url}/coins/{coin_id}/ohlc"
            params = {"vs_currency": "usd", "days": days}

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.get(url, params=params)
                    if response.status_code == 429:
                        logger.warning(f"CoinGecko rate-limited ({symbol} {timeframe}), retry {attempt}/{max_retries}...")
                        await asyncio.sleep(10.0)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    break  # success
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"CoinGecko fetch failed ({symbol} {timeframe}), retry {attempt}/{max_retries}: {e}")
                    await asyncio.sleep(10.0)
                    continue
                logger.error(f"CoinGecko fetch failed for {symbol} {timeframe}: {e}")
                return pl.DataFrame()
        else:
            logger.error(f"CoinGecko fetch failed for {symbol} {timeframe} after {max_retries} retries.")
            return pl.DataFrame()

        # ── Success path: build DataFrame from response data ──
        if not data or not isinstance(data, list):
            logger.warning(f"CoinGecko returned empty data for {symbol} {timeframe}")
            return pl.DataFrame()

        # CoinGecko OHLC format: [[timestamp_ms, open, high, low, close], ...]
        df = pl.DataFrame({
            "timestamp": [datetime.fromtimestamp(x[0] / 1000) for x in data],
            "open": [float(x[1]) for x in data],
            "high": [float(x[2]) for x in data],
            "low": [float(x[3]) for x in data],
            "close": [float(x[4]) for x in data],
            "volume": [0.0 for _ in data],  # CoinGecko OHLC has no volume
        })

        # Resample 5m → 15m if needed
        if timeframe == "15m":
            df = self._resample_5m_to_15m(df)
            logger.debug(f"Resampled 5m→15m: {len(df)} candles for {symbol}")

        # Trim to limit
        if len(df) > limit:
            df = df.tail(limit)

        logger.debug(f"Fetched {len(df)} candles for {symbol} {timeframe}")
        return df

    def _resample_5m_to_15m(self, df: pl.DataFrame) -> pl.DataFrame:
        """Resample 5-minute candles to 15-minute candles.

        Groups every 3 consecutive candles (sorted by time ascending)
        and computes OHLC from the group.
        """
        df = df.sort("timestamp")
        df = df.with_row_index()
        df = df.with_columns((pl.col("index") // 3).alias("_group"))
        resampled = df.group_by("_group", maintain_order=True).agg([
            pl.col("timestamp").first().alias("timestamp"),
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
        ]).drop("_group").sort("timestamp")
        return resampled

    async def fetch_current_prices(self) -> dict:
        """Fetch current USD prices for all tracked symbols.

        Lightweight endpoint suitable for frequent polling.
        Returns dict of {symbol: price}.
        """
        ids = list(self.SYMBOL_TO_ID.values())
        ids_str = ",".join(ids)
        url = f"{self.base_url}/simple/price?ids={ids_str}&vs_currencies=usd"

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

                # Invert the mapping: coin_id → symbol
                id_to_symbol = {v: k for k, v in self.SYMBOL_TO_ID.items()}
                prices = {}
                for coin_id, info in data.items():
                    symbol = id_to_symbol.get(coin_id)
                    if symbol and "usd" in info:
                        prices[symbol] = float(info["usd"])

                return prices
            except Exception as e:
                logger.warning(f"CoinGecko price fetch failed: {e}")
                return {}
