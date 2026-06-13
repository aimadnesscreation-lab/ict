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
from news_engine.engine import NewsEngine
from discord.bot import DiscordBot
from database.config import settings
from market_data.binance import BinanceCollector


async def analyze_timeframe(
    collector: BinanceCollector,
    symbol: str,
    tf: str,
    ict_ms: MarketStructure,
    ict_fvg: FVGDetector,
    ict_ob: OrderBlockDetector,
    ict_liquidity: LiquidityDetector,
    ict_sessions: SessionDetector,
    ict_pd: PremiumDiscountDetector,
    ict_breaker: BreakerBlockDetector,
    signal_engine: SignalEngine,
    news_sentiment: float,
) -> Dict:
    """Run full ICT analysis on a single timeframe and return a signal."""
    candle_limit = 500 if tf == "5m" else 300 if tf == "15m" else 200
    df = await collector.fetch_historical(symbol, tf, candle_limit)

    if df.is_empty():
        return {"score": 0, "signal_type": "NEUTRAL", "details": {}, "timeframe": tf}

    # Run full ICT pipeline
    df = ict_ms.detect_swings(df)
    df = ict_ms.detect_bos_mss(df)
    df = ict_fvg.detect_fvgs(df)
    df = ict_ob.detect_order_blocks(df)
    df = ict_liquidity.detect_all(df)
    df = ict_sessions.detect_sessions(df)
    df = ict_pd.compute_zones(df)
    df = ict_breaker.detect_breaker_blocks(df)

    has_mss = "mss" in df.columns and df["mss"].is_not_null().any()
    has_sweep = "liquidity_sweep_type" in df.columns and df["liquidity_sweep_type"].is_not_null().any()

    signal = signal_engine.generate_signal(
        df, mss=has_mss, sweep=has_sweep,
        news_sentiment=news_sentiment, timeframe=tf,
    )
    signal["symbol"] = symbol
    return signal


async def main():
    logger.info("Starting Institutional AI Trading Intelligence Platform...")

    logger.info("📡 Mode: LIVE MARKET DATA (Binance)")

    TIMEFRAMES = ["5m", "15m", "1h"]
    SIGNAL_SYMBOLS = ["BTCUSDT", "ETHUSDT"]

    collector = BinanceCollector(symbols=SIGNAL_SYMBOLS, timeframes=TIMEFRAMES)

    # ICT detectors
    ict_ms = MarketStructure(n=3)
    ict_fvg = FVGDetector()
    ict_ob = OrderBlockDetector()
    ict_liquidity = LiquidityDetector(atr_threshold=0.10)
    ict_sessions = SessionDetector()
    ict_pd = PremiumDiscountDetector()
    ict_breaker = BreakerBlockDetector()
    signal_engine = SignalEngine()
    news_engine = NewsEngine()

    # Discord
    discord_bot = None
    if settings.DISCORD_WEBHOOK_URL:
        discord_bot = DiscordBot(webhook_url=settings.DISCORD_WEBHOOK_URL)

    # Fetch news (shared across all timeframe analyses)
    news = await news_engine.fetch_news()
    if news:
        first_content = news[0].get("content", news[0].get("title", ""))
        sentiment = news_engine.analyze_sentiment(first_content)
        logger.info(f"Current Market Sentiment: {sentiment} (from {len(news)} articles)")
    else:
        sentiment = 0.0
        logger.info("No news articles available, using neutral sentiment.")

    # Analyze each symbol × timeframe combination
    all_signals = []
    for symbol in SIGNAL_SYMBOLS:
        for tf in TIMEFRAMES:
            signal = await analyze_timeframe(
                collector, symbol, tf,
                ict_ms, ict_fvg, ict_ob, ict_liquidity,
                ict_sessions, ict_pd, ict_breaker,
                signal_engine, sentiment,
            )
            all_signals.append(signal)
            logger.info(
                f"[{symbol} / {tf}] Signal: {signal['signal_type']} "
                f"(Score: {signal['score']}, Bias: {signal.get('bias', '?')})"
            )

    # Find the highest-confidence signal for Discord
    best = max(all_signals, key=lambda s: s.get("score", 0))
    logger.info(f"Best signal: {best['symbol']} / {best.get('timeframe', '?')} — {best['signal_type']} (Score: {best['score']})")

    if discord_bot and best.get("score", 0) >= 60:
        await discord_bot.send_signal(best)
    else:
        logger.warning("Discord not configured or signal too weak. Skipping alert.")

    logger.info("System cycle complete.")

if __name__ == "__main__":
    asyncio.run(main())
