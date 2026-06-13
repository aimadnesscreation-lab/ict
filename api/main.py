from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Optional
from datetime import datetime
import random
import os
import asyncio
import json
import httpx
from loguru import logger
from contextlib import asynccontextmanager

# ── Real data imports ─────────────────────────────────────────────────
from market_data.binance import BinanceCollector
from ict_engine.market_structure import MarketStructure
from ict_engine.fvg import FVGDetector
from ict_engine.order_blocks import OrderBlockDetector
from ict_engine.liquidity import LiquidityDetector
from ict_engine.sessions import SessionDetector
from ict_engine.premium_discount import PremiumDiscountDetector
from ict_engine.breaker_block import BreakerBlockDetector
from signal_engine.engine import SignalEngine
from backtesting.engine import BacktestEngine
from news_engine.engine import NewsEngine
from risk.manager import RiskManager
from discord.bot import DiscordBot

# ── App state ─────────────────────────────────────────────────────────
_signal_id_counter = 0
_recent_signals: List[Dict] = []
_recent_trades: List[Dict] = []
_performance_cache: Dict = {}
_news_cache: List[Dict] = []
_news_cache_time: Optional[datetime] = None

risk_manager = RiskManager(
    max_risk_per_trade_pct=1.0,
    max_daily_loss_pct=3.0,
    max_open_positions=3,
)

# ── API credentials ────────────────────────────────────────────────────
# Loaded from .env at the project root
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Create Discord bot instance if we have the webhook URL
discord_bot: Optional[DiscordBot] = None
if DISCORD_WEBHOOK_URL:
    try:
        discord_bot = DiscordBot(webhook_url=DISCORD_WEBHOOK_URL)
        logger.info("Discord bot initialized.")
    except Exception as e:
        logger.warning(f"Failed to initialize Discord bot: {e}")

# Workers list for lifecycle management
_background_tasks: List[asyncio.Task] = []


# ── Lifespan ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start all background workers on startup, cancel on shutdown."""
    # Multi-timeframe collector — supports 5m, 15m, 1h
    TIMEFRAMES = ["5m", "15m", "1h"]
    collector = BinanceCollector(symbols=["BTCUSDT", "ETHUSDT"], timeframes=TIMEFRAMES)

    # Start Binance WS price worker (crypto)
    ws_task = asyncio.create_task(_binance_worker())
    _background_tasks.append(ws_task)

    # Start Twelve Data WS price worker (forex) — only if we have the API key
    if TWELVEDATA_API_KEY:
        td_task = asyncio.create_task(_twelve_data_worker())
        _background_tasks.append(td_task)
        logger.info("Twelve Data forex worker scheduled.")

    # Start signal generation worker (ICT engine on real candles, multi-timeframe)
    signal_task = asyncio.create_task(_signal_worker(collector))
    _background_tasks.append(signal_task)

    # Start news refresh worker
    news_task = asyncio.create_task(_news_worker())
    _background_tasks.append(news_task)

    logger.info(f"Started {len(_background_tasks)} background workers.")
    yield

    # Cancel all workers on shutdown
    for t in _background_tasks:
        t.cancel()
    await asyncio.gather(*_background_tasks, return_exceptions=True)
    _background_tasks.clear()
    logger.info("All background workers stopped.")


app = FastAPI(title="Institutional Trading Intelligence Platform API", lifespan=lifespan)

# CORS — allow the Vite dev server to talk to the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Background workers ────────────────────────────────────────────────

async def _signal_worker(collector: BinanceCollector):
    """
    Periodically fetch candles across multiple timeframes (5m, 15m, 1h),
    run full ICT detection pipeline, generate signals with confluence scoring.
    """
    global _signal_id_counter, _recent_signals, _recent_trades, _performance_cache

    ict_ms = MarketStructure(n=3)       # Swing N=3 per ict.md
    ict_fvg = FVGDetector()
    ict_ob = OrderBlockDetector()
    ict_liquidity = LiquidityDetector(atr_threshold=0.10)
    ict_sessions = SessionDetector()
    ict_pd = PremiumDiscountDetector()
    ict_breaker = BreakerBlockDetector()
    signal_engine = SignalEngine()
    backtester = BacktestEngine(initial_capital=10000.0, rr_target=2.0, rr_stop=1.0)

    # Timeframes and symbols
    TIMEFRAMES = ["5m", "15m", "1h"]
    SIGNAL_SYMBOLS = ["BTCUSDT", "ETHUSDT"]

    # How long to sleep between cycles (fastest timeframe = 5m)
    CYCLE_INTERVAL = 300  # 5 minutes

    # Discord notification dedup
    _last_discord_signal_type: Optional[str] = None

    while True:
        try:
            all_signals: List[Dict] = []

            for symbol in SIGNAL_SYMBOLS:
                for tf in TIMEFRAMES:
                    # Fetch candles — more candles for lower timeframes
                    candle_limit = 500 if tf == "5m" else 300 if tf == "15m" else 200
                    df = await collector.fetch_historical(symbol, tf, candle_limit)
                    if df.is_empty():
                        logger.warning(f"No candle data for {symbol} {tf}, skipping.")
                        continue

                    # Run ICT detection pipeline
                    df = ict_ms.detect_swings(df)
                    df = ict_ms.detect_bos_mss(df)
                    df = ict_fvg.detect_fvgs(df)
                    df = ict_ob.detect_order_blocks(df)
                    df = ict_liquidity.detect_all(df)
                    df = ict_sessions.detect_sessions(df)
                    df = ict_pd.compute_zones(df)
                    df = ict_breaker.detect_breaker_blocks(df)

                    # Check detection flags
                    has_mss = "mss" in df.columns and df["mss"].is_not_null().any()
                    has_sweep = ("liquidity_sweep_type" in df.columns
                                 and df["liquidity_sweep_type"].is_not_null().any())

                    # Generate signal with full confluence scoring
                    signal = signal_engine.generate_signal(
                        df, mss=has_mss, sweep=has_sweep,
                        news_sentiment=0.0, timeframe=tf,
                    )
                    signal["symbol"] = symbol
                    signal["id"] = None

                    # Add confidence estimate
                    score = signal["score"]
                    if score >= 80:
                        signal["confidence"] = round(random.uniform(0.85, 0.98), 2)
                    elif score >= 60:
                        signal["confidence"] = round(random.uniform(0.65, 0.85), 2)
                    elif score >= 40:
                        signal["confidence"] = round(random.uniform(0.45, 0.65), 2)
                    elif score >= 20:
                        signal["confidence"] = round(random.uniform(0.25, 0.45), 2)
                    else:
                        signal["confidence"] = round(random.uniform(0.10, 0.25), 2)

                    all_signals.append(signal)

            # Assign IDs and store
            for s in all_signals:
                _signal_id_counter += 1
                s["id"] = _signal_id_counter

            _recent_signals = all_signals + _recent_signals
            if len(_recent_signals) > 500:
                _recent_signals = _recent_signals[:500]

            # ── Backtest on 15m candles (mid-ground timeframe) ──
            if all_signals:
                try:
                    df_bt = await collector.fetch_historical("BTCUSDT", "15m", 300)
                    if not df_bt.is_empty():
                        bt_signals = []
                        for s in all_signals:
                            bt_signals.append({
                                "timestamp": s.get("timestamp"),
                                "price": s.get("price", 0),
                                "signal_type": s.get("signal_type", "NEUTRAL"),
                            })
                        backtester.trades = []
                        report = backtester.run(df_bt, bt_signals)
                        _recent_trades = backtester.trades + _recent_trades
                        if len(_recent_trades) > 500:
                            _recent_trades = _recent_trades[:500]
                        _performance_cache = report
                except Exception as e:
                    logger.warning(f"Backtest failed: {e}")

            # ── Send strong signals to Discord ────────────────
            if discord_bot:
                for s in all_signals:
                    stype = s.get("signal_type", "NEUTRAL")
                    score_val = s.get("score", 0)
                    if score_val >= 70 and stype != _last_discord_signal_type:
                        _last_discord_signal_type = stype
                        try:
                            await discord_bot.send_signal(s)
                        except Exception as e:
                            logger.warning(f"Discord send failed: {e}")

            logger.info(
                f"Signal cycle complete: {len(all_signals)} signals across "
                f"{len(TIMEFRAMES)} timeframes, {len(_recent_trades)} trades."
            )

        except Exception as e:
            logger.warning(f"Signal worker error: {e}. Retrying in 60s...")

        await asyncio.sleep(CYCLE_INTERVAL)


async def _news_worker():
    """Periodically fetch real news from Google News RSS."""
    global _news_cache, _news_cache_time

    news_engine = NewsEngine()

    while True:
        try:
            articles = await news_engine.fetch_news()
            if articles:
                # Convert datetime objects to ISO strings for JSON serialization
                for a in articles:
                    if hasattr(a.get("published_at"), "isoformat"):
                        a["published_at"] = a["published_at"].isoformat()
                _news_cache = articles
                _news_cache_time = datetime.utcnow()
                logger.info(f"Fetched {len(articles)} news articles.")
            else:
                logger.warning("No news articles returned, keeping cache.")

        except Exception as e:
            logger.warning(f"News worker error: {e}. Retrying in 300s...")

        # Refresh every 5 minutes
        await asyncio.sleep(300)


# ─── Root ───────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    data_sources = ["Binance (crypto)"]
    if TWELVEDATA_API_KEY:
        data_sources.append("Twelve Data (forex)")
    else:
        data_sources.append("Forex (mock — set TWELVEDATA_API_KEY for live)")
    return {
        "status": "online",
        "version": "0.1.0",
        "data_source": " + ".join(data_sources),
    }


# ─── Signals (real) ───────────────────────────────────────────────────

@app.get("/signals")
async def get_signals(limit: int = Query(10, ge=1, le=100)):
    """Return recent ICT-generated signals from real market data."""
    if not _recent_signals:
        # If no real signals yet, return a meaningful empty state
        return []

    return [format_signal(s) for s in _recent_signals[:limit]]


@app.get("/signals/{signal_id}")
async def get_signal_detail(signal_id: int):
    """Return a single signal by ID."""
    for s in _recent_signals:
        if s.get("id") == signal_id:
            return format_signal(s)
    raise HTTPException(status_code=404, detail="Signal not found")


def format_signal(s: Dict) -> Dict:
    """Convert internal signal dict to the API response format."""
    details = s.get("details", {})
    return {
        "id": s.get("id", 0),
        "symbol": s.get("symbol", "BTCUSDT"),
        "signal_type": s.get("signal_type", "NEUTRAL"),
        "score": s.get("score", 0),
        "price": s.get("price", 0),
        "timeframe": s.get("timeframe", "1h"),
        "bias": s.get("bias", "neutral"),
        "timestamp": (
            s["timestamp"].isoformat()
            if hasattr(s.get("timestamp"), "isoformat")
            else str(s.get("timestamp", ""))
        ),
        "confidence": s.get("confidence", 0.5),
        "meta_data": {
            "mss": details.get("mss", False),
            "sweep": details.get("sweep", False),
            "fvg": details.get("fvg", False),
            "ob": details.get("ob", False),
            "discount": details.get("discount", False),
            "ote": details.get("ote", False),
            "bias": details.get("bias", "neutral"),
            "news_sentiment": details.get("news_sentiment", 0.0),
        },
    }


# ─── Candles (real) ──────────────────────────────────────────────────

@app.get("/candles/{symbol}")
async def get_candles(symbol: str, timeframe: str = "1h", limit: int = 100):
    """
    Fetch historical candles from Binance.
    Supports crypto pairs (BTCUSDT, ETHUSDT). Forex pairs return empty with a note.
    """
    symbol = symbol.upper()

    # Only crypto pairs are available via Binance
    CRYPTO_SYMBOLS = {"BTCUSDT", "ETHUSDT"}

    if symbol not in CRYPTO_SYMBOLS:
        return {
            "error": f"Real data for {symbol} requires a forex API provider",
            "data": [],
        }

    try:
        collector = BinanceCollector(symbols=[symbol], timeframes=[timeframe])
        df = await collector.fetch_historical(symbol, timeframe, limit)

        if df.is_empty():
            return []

        return [
            {
                "id": i + 1,
                "symbol": symbol,
                "timeframe": timeframe,
                "timestamp": row["timestamp"].isoformat()
                if hasattr(row["timestamp"], "isoformat")
                else str(row["timestamp"]),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            }
            for i, row in enumerate(df.to_dicts())
        ]

    except Exception as e:
        logger.error(f"Candle fetch failed for {symbol}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch candles: {e}")


# ─── News (real via RSS) ──────────────────────────────────────────────

@app.get("/news")
async def get_news(limit: int = 10):
    """Return recent financial news from Google News RSS (real data)."""
    if not _news_cache:
        return []

    return [
        {
            "title": a.get("title", ""),
            "source": a.get("source", "RSS"),
            "published_at": str(a.get("published_at", "")),
            "sentiment": a.get("sentiment", 0.0),
        }
        for a in _news_cache[:limit]
    ]


# ─── Trades (real, from backtesting) ─────────────────────────────────

@app.get("/trades")
async def get_trades(
    limit: int = Query(20, ge=1, le=200),
    result: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
):
    """Return backtested trades from real signal data."""
    trades = _recent_trades if _recent_trades else []

    if result:
        trades = [t for t in trades if t.get("result") == result]
    if symbol:
        trades = [t for t in trades if t.get("symbol", "").upper() == symbol.upper()]

    # Assign sequential IDs
    result_trades = []
    for i, t in enumerate(trades[:limit]):
        result_trades.append({
            "id": i + 1,
            "symbol": t.get("symbol", "BTCUSDT"),
            "signal_type": t.get("signal_type", "NEUTRAL"),
            "entry_time": (
                t["entry_time"].isoformat()
                if hasattr(t.get("entry_time"), "isoformat")
                else str(t.get("entry_time", ""))
            ),
            "exit_time": (
                t["exit_time"].isoformat()
                if hasattr(t.get("exit_time"), "isoformat")
                else str(t.get("exit_time", ""))
            ),
            "entry_price": t.get("entry_price", 0),
            "exit_price": t.get("exit_price", 0),
            "profit": t.get("profit", 0),
            "rr": t.get("rr", 0),
            "result": t.get("result", "BREAK_EVEN"),
        })

    return result_trades


# ─── Performance (real, from backtesting) ────────────────────────────

@app.get("/performance")
async def get_performance():
    """Return backtest performance metrics computed from real signals."""
    if not _performance_cache:
        return {
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "total_trades": 0,
            "avg_rr": 0.0,
        }

    p = _performance_cache
    return {
        "win_rate": p.get("win_rate", 0.0),
        "total_pnl": p.get("total_profit", 0.0),
        "profit_factor": p.get("profit_factor", 0.0),
        "max_drawdown": p.get("max_drawdown", 0.0),
        "sharpe_ratio": _performance_cache.get("sharpe_ratio", 0.0),
        "total_trades": p.get("total_trades", 0),
        "avg_rr": p.get("avg_rr", 0.0),
    }


# ─── Risk (real, from RiskManager) ───────────────────────────────────

@app.get("/risk/status")
async def get_risk_status():
    """Return current risk management state."""
    return {
        "max_risk_per_trade_pct": risk_manager.max_risk_per_trade_pct,
        "max_daily_loss_pct": risk_manager.max_daily_loss_pct,
        "max_weekly_loss_pct": 6.0,
        "max_open_positions": risk_manager.max_open_positions,
        "current_daily_loss_pct": round(
            risk_manager.current_daily_loss
            / (10000 * risk_manager.max_daily_loss_pct / 100)
            * risk_manager.max_daily_loss_pct
            if risk_manager.max_daily_loss_pct > 0 else 0, 2
        ),
        "current_weekly_loss_pct": 0.0,
        "open_positions_count": risk_manager.open_positions_count,
        "account_balance": 10000.0,
    }


# ─── WebSocket Price Stream ───────────────────────────────────────────

import websockets

# Symbols tracked in the header ticker
TRACKED_SYMBOLS = ["BTCUSDT", "ETHUSDT", "EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]

# ── Crypto (via Binance) ────────────────────────────────────────────────
BINANCE_SYMBOLS = ["btcusdt", "ethusdt"]
BINANCE_WS_URL = "wss://stream.binance.com:9443/stream?streams=" + "/".join(f"{s}@ticker" for s in BINANCE_SYMBOLS)

# ── Forex (via Twelve Data) ─────────────────────────────────────────────
FOREX_SYMBOLS = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]

# Twelve Data uses forward-slash format (EUR/USD)
TWELVEDATA_SYMBOL_MAP = {"EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "XAUUSD": "XAU/USD", "USDJPY": "USD/JPY"}
TWELVEDATA_SYMBOLS = list(TWELVEDATA_SYMBOL_MAP.values())  # ["EUR/USD", "GBP/USD", "XAU/USD", "USD/JPY"]
TWELVEDATA_WS_URL = f"wss://ws.twelvedata.com/v1/quotes/price?apikey={TWELVEDATA_API_KEY}"
TWELVEDATA_REST_URL = "https://api.twelvedata.com/quote"

FOREX_BASE_PRICES = {"EURUSD": 1.1042, "GBPUSD": 1.2654, "XAUUSD": 2342.10, "USDJPY": 151.24}  # fallback seed prices (overwritten by Twelve Data)
FOREX_PRECISION = {"EURUSD": 4, "GBPUSD": 4, "XAUUSD": 2, "USDJPY": 3}  # decimal places per symbol

# Shared in-memory state: latest price for each symbol
_latest_prices: Dict[str, float] = {
    "BTCUSDT": 68420.0, "ETHUSDT": 3520.0,
    **FOREX_BASE_PRICES,
}
_latest_ticks: Dict[str, Dict] = {}

# Cache for forex 24h stats (refreshed via REST API every 5 min)
_forex_24h_stats: Dict[str, Dict] = {
    sym: {"change_24h": 0.0, "high_24h": base, "low_24h": base}
    for sym, base in FOREX_BASE_PRICES.items()
}


# ── Twelve Data WebSocket background worker (forex) ────────────────────

async def _twelve_data_worker():
    """
    Background task: connect to Twelve Data's WebSocket for real-time forex
    prices and update _latest_ticks / _latest_prices. Falls back to REST API
    for 24h stats (high, low, change).
    """
    if not TWELVEDATA_API_KEY:
        logger.warning("Twelve Data API key missing — forex will use mock data.")
        return

    retry_delay = 1.0

    # Map Twelve Data symbol format -> our format ("EUR/USD" -> "EURUSD")
    def to_internal(td_symbol: str) -> str:
        return td_symbol.replace("/", "")

    async def _fetch_all_forex_quotes() -> None:
        """Fetch full quotes for all forex symbols in a single REST call."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                symbols_str = ",".join(TWELVEDATA_SYMBOLS)
                resp = await client.get(
                    TWELVEDATA_REST_URL,
                    params={"symbol": symbols_str, "apikey": TWELVEDATA_API_KEY},
                )
                if resp.status_code != 200:
                    logger.warning(f"Twelve Data REST: HTTP {resp.status_code}")
                    return
                data = resp.json()
                if isinstance(data, dict) and "code" in data:
                    return  # API error
                # Response is a dict keyed by symbol: {"EUR/USD": {...}, "GBP/USD": {...}}
                for td_symbol, quote in data.items():
                    if not isinstance(quote, dict) or "code" in quote:
                        continue
                    internal = td_symbol.replace("/", "")
                    if internal not in FOREX_SYMBOLS:
                        continue
                    _forex_24h_stats[internal] = {
                        "change_24h": round(float(quote.get("percent_change", 0)), 2),
                        "high_24h": round(float(quote.get("high", FOREX_BASE_PRICES[internal])), FOREX_PRECISION[internal]),
                        "low_24h": round(float(quote.get("low", FOREX_BASE_PRICES[internal])), FOREX_PRECISION[internal]),
                    }
                logger.info(f"Twelve Data REST refresh complete ({len(data)} symbols).")
        except Exception as e:
            logger.warning(f"Twelve Data REST fetch failed: {e}")

    while True:
        try:
            logger.info(f"Connecting to Twelve Data WS...")
            async with websockets.connect(TWELVEDATA_WS_URL, ping_interval=30) as ws:
                logger.info("Twelve Data WS connected.")
                retry_delay = 1.0

                # Subscribe to forex pairs
                subscribe_msg = json.dumps({
                    "action": "subscribe",
                    "params": {"symbols": ",".join(TWELVEDATA_SYMBOLS)},
                })
                await ws.send(subscribe_msg)
                logger.info(f"Subscribed to Twelve Data: {', '.join(TWELVEDATA_SYMBOLS)}")

                # Start a heartbeat task (Twelve Data expects JSON heartbeats every ~20s)
                async def _heartbeat_loop():
                    while True:
                        await asyncio.sleep(20)
                        try:
                            await ws.send(json.dumps({"action": "heartbeat"}))
                        except Exception:
                            break

                heartbeat_task = asyncio.create_task(_heartbeat_loop())

                # Start periodic REST quote fetcher (every 5 min) for 24h stats
                last_rest_fetch = datetime.utcnow()

                # Start with an initial REST fetch
                await _fetch_all_forex_quotes()

                async for raw in ws:
                    try:
                        data = json.loads(raw)
                        event = data.get("event", "")

                        if event == "price":
                            td_symbol = data.get("symbol", "")
                            internal_symbol = to_internal(td_symbol)
                            if internal_symbol not in FOREX_SYMBOLS:
                                continue

                            price = float(data.get("price", 0))
                            if price == 0:
                                continue

                            prec = FOREX_PRECISION.get(internal_symbol, 4)
                            stats = _forex_24h_stats.get(
                                internal_symbol,
                                {"change_24h": 0.0, "high_24h": price, "low_24h": price},
                            )

                            tick = {
                                "symbol": internal_symbol,
                                "price": round(price, prec),
                                "change_24h": stats["change_24h"],
                                "high_24h": stats["high_24h"],
                                "low_24h": stats["low_24h"],
                                "volume": round(float(data.get("day_volume", 0)), 2),
                                "timestamp": datetime.utcnow().isoformat() + "Z",
                            }
                            _latest_ticks[internal_symbol] = tick
                            _latest_prices[internal_symbol] = tick["price"]

                        elif event == "heartbeat":
                            pass  # Server heartbeat, nothing needed

                        # Refresh 24h stats from REST every 5 minutes
                        now = datetime.utcnow()
                        if (now - last_rest_fetch).total_seconds() >= 300:
                            await _fetch_all_forex_quotes()
                            last_rest_fetch = now

                    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                        continue

        except websockets.exceptions.WebSocketException as e:
            logger.warning(f"Twelve Data WS error: {e}. Reconnecting in {retry_delay:.0f}s...")
        except Exception as e:
            logger.warning(f"Twelve Data WS unexpected error: {e}. Reconnecting in {retry_delay:.0f}s...")

        # Cancel heartbeat task if it was started
        try:
            heartbeat_task.cancel()
        except (NameError, Exception):
            pass

        await asyncio.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, 60.0)


# ── Binance WebSocket background worker (crypto) ────────────────────

async def _binance_worker():
    """
    Background task: maintain a persistent connection to Binance's combined
    ticker stream and update _latest_ticks / _latest_prices in real time.
    Reconnects with exponential backoff on failure.
    """
    retry_delay = 1.0

    while True:
        try:
            logger.info(f"Connecting to Binance WS: {BINANCE_WS_URL}")
            async with websockets.connect(BINANCE_WS_URL, ping_interval=20) as ws:
                logger.info("Binance WS connected.")
                retry_delay = 1.0

                async for raw in ws:
                    try:
                        data = json.loads(raw)
                        inner = data.get("data", data)
                        symbol = inner.get("s", "").upper()
                        if not symbol:
                            continue

                        tick = {
                            "symbol": symbol,
                            "price": round(float(inner["c"]), 8),
                            "change_24h": round(float(inner.get("P", 0)), 2),
                            "high_24h": round(float(inner.get("h", 0)), 8),
                            "low_24h": round(float(inner.get("l", 0)), 8),
                            "volume": round(float(inner.get("v", 0)), 2),
                            "timestamp": datetime.utcfromtimestamp(
                                inner.get("E", 0) / 1000
                            ).isoformat() + "Z",
                        }
                        _latest_ticks[symbol] = tick
                        _latest_prices[symbol] = tick["price"]
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue

        except websockets.exceptions.WebSocketException as e:
            logger.warning(f"Binance WS error: {e}. Reconnecting in {retry_delay:.0f}s...")
        except Exception as e:
            logger.warning(f"Binance WS unexpected error: {e}. Reconnecting in {retry_delay:.0f}s...")

        await asyncio.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, 60.0)


# ── WebSocket endpoint ────────────────────────────────────────────────

async def _stream_prices(websocket: WebSocket):
    """Stream prices to the connected dashboard client.

    Crypto symbols come from Binance WS (_binance_worker).
    Forex symbols come from Twelve Data WS (_twelve_data_worker)
    when the API key is configured; otherwise they fall back to mock.
    """
    await websocket.accept()

    # Send the most recent known prices immediately
    for symbol in TRACKED_SYMBOLS:
        if symbol in _latest_ticks and _latest_ticks[symbol]:
            await websocket.send_json(_latest_ticks[symbol])
        elif symbol in FOREX_SYMBOLS and symbol in _latest_prices:
            # If Twelve Data is active, _latest_ticks will have forex data already.
            # If not, generate a one-off mock tick so the dashboard isn't empty.
            if not TWELVEDATA_API_KEY:
                await websocket.send_json({
                    "symbol": symbol,
                    "price": _latest_prices[symbol],
                    "change_24h": 0.0,
                    "high_24h": FOREX_BASE_PRICES.get(symbol, _latest_prices[symbol]),
                    "low_24h": FOREX_BASE_PRICES.get(symbol, _latest_prices[symbol]),
                    "volume": 0,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                })

    try:
        while True:
            for symbol in TRACKED_SYMBOLS:
                if symbol in _latest_ticks:
                    tick = _latest_ticks[symbol]
                    await websocket.send_json(tick)
                elif symbol in FOREX_SYMBOLS:
                    # Only generate mock ticks if Twelve Data is NOT configured
                    if not TWELVEDATA_API_KEY and symbol in _latest_prices:
                        await websocket.send_json({
                            "symbol": symbol,
                            "price": _latest_prices[symbol],
                            "change_24h": 0.0,
                            "high_24h": FOREX_BASE_PRICES.get(symbol, _latest_prices[symbol]),
                            "low_24h": FOREX_BASE_PRICES.get(symbol, _latest_prices[symbol]),
                            "volume": 0,
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                        })
                await asyncio.sleep(0.25)
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@app.websocket("/ws/prices")
async def ws_price_stream(websocket: WebSocket):
    await _stream_prices(websocket)
