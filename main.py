import asyncio
from typing import Dict
import polars as pl
from loguru import logger
from ict_engine.market_structure import MarketStructure
from ict_engine.fvg import FVGDetector
from ict_engine.order_blocks import OrderBlockDetector
from ict_engine.liquidity import LiquidityDetector
from ict_engine.sessions import SessionDetector
from ict_engine.premium_discount import PremiumDiscountDetector
from ict_engine.breaker_block import BreakerBlockDetector
from signal_engine.engine import SignalEngine

async def main():
    logger.info("This script (main.py) is deprecated. Use the API server instead: uvicorn api.main:app")
    logger.info("The production system runs via api/main.py with OKX data.")

if __name__ == "__main__":
    asyncio.run(main())
