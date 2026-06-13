import asyncio
from loguru import logger
from market_data.collector import MockCollector
from ict_engine.market_structure import MarketStructure
from ict_engine.fvg import FVGDetector
from ict_engine.order_blocks import OrderBlockDetector
from signal_engine.engine import SignalEngine
from news_engine.engine import NewsEngine
from telegram.bot import TelegramBot
from database.config import settings

import os
from market_data.binance import BinanceCollector

async def main():
    logger.info("Starting Institutional AI Trading Intelligence Platform...")
    
    # Toggle for Live Data (controlled via ENV variable)
    USE_LIVE_DATA = os.getenv("LIVE_DATA", "false").lower() == "true"

    # 1. Initialize Engines
    if USE_LIVE_DATA:
        logger.info("📡 Mode: LIVE MARKET DATA (Binance)")
        collector = BinanceCollector(symbols=["BTCUSDT", "ETHUSDT"], timeframes=["1h"])
    else:
        logger.warning("🧪 Mode: MOCK DATA (Simulation)")
        collector = MockCollector(symbols=["EURUSD"], timeframes=["1h"])
    ict_ms = MarketStructure(n=2)
    ict_fvg = FVGDetector()
    ict_ob = OrderBlockDetector()
    signal_engine = SignalEngine()
    news_engine = NewsEngine()
    
    # Telegram (optional based on env)
    telegram = None
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        telegram = TelegramBot(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID)

    # 2. Fetch Initial Data
    df = await collector.fetch_historical("EURUSD", "1h", limit=100)
    logger.info(f"Fetched {len(df)} candles.")

    # 3. Process ICT Logic
    df = ict_ms.detect_swings(df)
    df = ict_fvg.detect_fvgs(df)
    df = ict_ob.detect_order_blocks(df)
    
    # 4. Process News
    news = await news_engine.fetch_news()
    sentiment = news_engine.analyze_sentiment(news[0]["content"])
    logger.info(f"Current Market Sentiment: {sentiment}")

    # 5. Generate Signal
    # Mocking some confluences for demonstration
    signal = signal_engine.generate_signal(df, mss=True, sweep=True, news_sentiment=sentiment)
    signal["symbol"] = "EURUSD"
    
    logger.info(f"Generated Signal: {signal['signal_type']} (Score: {signal['score']})")

    # 6. Notify
    if telegram:
        await telegram.send_signal(signal)
    else:
        logger.warning("Telegram not configured. Skipping alert.")

    logger.info("System cycle complete.")

if __name__ == "__main__":
    asyncio.run(main())
