import asyncio
from loguru import logger
import polars as pl
from market_data.binance import BinanceCollector
from ict_engine.market_structure import MarketStructure
from ict_engine.fvg import FVGDetector
from ict_engine.order_blocks import OrderBlockDetector
from ict_engine.liquidity import LiquidityDetector
from signal_engine.engine import SignalEngine
from news_engine.engine import NewsEngine

async def run_smoke_test():
    logger.info("🚀 Starting End-to-End System Smoke Test...")

    try:
        # 1. Market Data Collection
        logger.info("Step 1: Fetching real data from Binance...")
        collector = BinanceCollector(symbols=["BTCUSDT"], timeframes=["1h"])
        df = await collector.fetch_historical("BTCUSDT", "1h", limit=100)
        
        if df.is_empty():
            raise Exception("Failed to fetch data from Binance.")
        logger.info(f"✅ Successfully fetched {len(df)} candles.")

        # 2. ICT Engine Analysis
        logger.info("Step 2: Running ICT Engine analysis...")
        ms = MarketStructure(n=2)
        fvg = FVGDetector()
        ob = OrderBlockDetector()
        liquidity = LiquidityDetector()
        
        df = ms.detect_swings(df)
        df = ms.detect_bos_mss(df)
        df = fvg.detect_fvgs(df)
        df = ob.detect_order_blocks(df)
        df = liquidity.detect_all(df)
        
        logger.info("✅ ICT Analysis complete. Columns: " + ", ".join(df.columns))

        # 3. News & Sentiment
        logger.info("Step 3: Analyzing market sentiment...")
        news_engine = NewsEngine()
        news = await news_engine.fetch_news()
        sentiment = news_engine.analyze_sentiment(news[0]["content"])
        logger.info(f"✅ Sentiment analysis complete: {sentiment}")

        # 4. Signal Generation
        logger.info("Step 4: Generating trading signals...")
        engine = SignalEngine()
        # Check if we have any detections to pass
        has_mss = df["mss"].is_not_null().any() if "mss" in df.columns else False
        has_sweep = df["liquidity_sweep_type"].is_not_null().any() if "liquidity_sweep_type" in df.columns else False
        
        signal = engine.generate_signal(df, mss=has_mss, sweep=has_sweep, news_sentiment=sentiment)
        signal["symbol"] = "BTCUSDT"
        
        logger.info(f"✅ Signal Engine output: {signal['signal_type']} (Score: {signal['score']})")

        logger.info("🎉 Smoke Test PASSED! The system is correctly wired.")
        
    except Exception as e:
        logger.error(f"❌ Smoke Test FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_smoke_test())
