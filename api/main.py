from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Optional
from datetime import datetime
import random
import os
import time
import asyncio
import json
import httpx
import polars as pl
from loguru import logger
from contextlib import asynccontextmanager

# ── Real data imports ─────────────────────────────────────────────────
from market_data.coingecko import CoinGeckoCollector
from ict_engine.market_structure import MarketStructure
from ict_engine.fvg import FVGDetector
from ict_engine.order_blocks import OrderBlockDetector
from ict_engine.liquidity import LiquidityDetector
from ict_engine.sessions import SessionDetector
from ict_engine.premium_discount import PremiumDiscountDetector
from ict_engine.breaker_block import BreakerBlockDetector
from news_engine.engine import NewsEngine
from risk.manager import RiskManager
from discord.bot import DiscordBot
from demo_account import DemoAccount
from signal_engine.engine import SignalEngine, determine_bias_from_swings, determine_bias_from_ema

# ── App state ─────────────────────────────────────────────────────────
_signal_id_counter = 0
_recent_signals: List[Dict] = []
_recent_trades: List[Dict] = []
_performance_cache: Dict = {}
_news_cache: List[Dict] = []
_news_cache_time: Optional[datetime] = None

# Health / debugging state
_health: Dict = {
    "status": "starting",
    "htf_bias": "neutral",
    "last_cycle_time": None,
    "cycle_count": 0,
    "last_error_time": None,
    "last_error_message": None,
    "total_signals_generated": 0,
    "total_signals_kept": 0,
    "total_trades_executed": 0,
    "started_at": datetime.utcnow().isoformat() + "Z",
    "data_sources": [],
}

risk_manager = RiskManager(
    max_risk_per_trade_pct=1.0,
    max_daily_loss_pct=3.0,
    max_open_positions=3,
)

# ── ICT detectors (shared across all workers, created once) ─────────
_ict_ms = MarketStructure(n=3)
_ict_fvg = FVGDetector()
_ict_ob = OrderBlockDetector()
_ict_liquidity = LiquidityDetector(atr_threshold=0.10)
_ict_sessions = SessionDetector()
_ict_pd = PremiumDiscountDetector()
_ict_breaker = BreakerBlockDetector()
_signal_engine = SignalEngine()
_demo_account = DemoAccount(
    initial_balance=10_000.0, risk_per_trade_pct=1.0,
    max_daily_loss_pct=risk_manager.max_daily_loss_pct,
    max_open_positions=risk_manager.max_open_positions,
)

# ── Binance crypto data ──────────────────────────────────────────────
BINANCE_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
BINANCE_TIMEFRAMES = ["1m", "5m", "15m"]
BINANCE_BUFFER_LIMITS = {"1m": 360, "5m": 288, "15m": 168}  # candles per buffer

# Candle buffers: _candle_buffers[symbol][timeframe] = List[Dict]
_candle_buffers: Dict[str, Dict[str, List[Dict]]] = {}

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

    # Start Binance WS crypto worker (real-time 1m/5m/15m candles + ticker)
    # No API key needed — replaces old CoinGecko polling
    binance_task = asyncio.create_task(_binance_crypto_worker())
    _background_tasks.append(binance_task)
    logger.info("Binance crypto WS worker scheduled (real-time 1m/5m/15m).")

    # Start HTF bias worker (CoinGecko 1h data, updates every 15 min)
    bias_task = asyncio.create_task(_htf_bias_worker())
    _background_tasks.append(bias_task)
    logger.info("HTF bias worker scheduled (CoinGecko 1h, 15min cycle).")

    # Start Twelve Data WS price worker (forex) — only if we have the API key
    if TWELVEDATA_API_KEY:
        td_task = asyncio.create_task(_twelve_data_worker())
        _background_tasks.append(td_task)
        logger.info("Twelve Data forex worker scheduled.")

    # Start news refresh worker
    news_task = asyncio.create_task(_news_worker())
    _background_tasks.append(news_task)

    # Health tracking
    _health["data_sources"] = ["Binance WS (crypto)"]
    if TWELVEDATA_API_KEY:
        _health["data_sources"].append("Twelve Data (forex)")
    _health["status"] = "running"

    logger.info(f"Started {len(_background_tasks)} background workers.")
    yield

    # Cancel all workers on shutdown
    for t in _background_tasks:
        t.cancel()
    await asyncio.gather(*_background_tasks, return_exceptions=True)
    _background_tasks.clear()
    logger.info("All background workers stopped.")


app = FastAPI(title="Institutional Trading Intelligence Platform API", lifespan=lifespan)

# CORS — allow the Vite dev server and Railway domain to talk to the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://ict-production-b1a8.up.railway.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Background workers ────────────────────────────────────────────────

# ── Binance WebSocket Worker (real-time crypto data + signals) ─────────

# Binance combined streams URL — no API key needed
BINANCE_WS_URL = "wss://stream.binance.com:9443/stream"


def _binance_streams() -> str:
    """Build the combined streams path for all symbols + timeframes + ticker."""
    pairs = []
    for sym in BINANCE_SYMBOLS:
        s = sym.lower()
        for tf in ["1m", "5m", "15m"]:
            pairs.append(f"{s}@kline_{tf}")
        pairs.append(f"{s}@ticker")
    return "/".join(pairs)


async def _backfill_crypto_buffers():
    """Backfill 5m and 15m buffers from CoinGecko on startup."""
    global _candle_buffers
    collector = CoinGeckoCollector(symbols=BINANCE_SYMBOLS, timeframes=["5m"])
    for symbol in BINANCE_SYMBOLS:
        df_5m = await collector.fetch_historical(symbol, "5m", 288)
        if not df_5m.is_empty():
            buf = []
            for row in df_5m.to_dicts():
                buf.append({
                    "timestamp": row["timestamp"],
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row["volume"],
                })
            _candle_buffers.setdefault(symbol, {})["5m"] = buf
            logger.info(f"[Binance] Backfilled {len(buf)} 5m candles for {symbol}")
        _candle_buffers.setdefault(symbol, {}).setdefault("1m", [])
        _candle_buffers.setdefault(symbol, {}).setdefault("15m", [])


def _append_to_buffer(symbol: str, tf: str, candle: Dict):
    buf = _candle_buffers.setdefault(symbol, {}).setdefault(tf, [])
    # Replace if last candle has same timestamp (avoid duplicates from backfill/WS overlap)
    if buf and buf[-1]["timestamp"] == candle["timestamp"]:
        buf[-1] = candle
    else:
        buf.append(candle)
    limit = BINANCE_BUFFER_LIMITS.get(tf, 288)
    if len(buf) > limit:
        buf[:] = buf[-limit:]


def _buffer_to_df(symbol: str, tf: str) -> pl.DataFrame:
    buf = _candle_buffers.get(symbol, {}).get(tf, [])
    if len(buf) < 10:
        return pl.DataFrame()
    return pl.DataFrame(buf)


async def _run_crypto_analysis(symbol: str, tf_closed: str):
    """
    Called when a candle closes on Binance.
    Runs the ICT pipeline, generates signals, processes demo account, sends Discord.
    """
    global _signal_id_counter, _recent_signals, _recent_trades, _performance_cache

    htf_bias = _health.get("htf_bias", "neutral")
    all_signals: List[Dict] = []

    tfs_to_analyze = ["5m", "15m"]
    if tf_closed == "1m":
        tfs_to_analyze = ["1m", "5m", "15m"]

    for tf in tfs_to_analyze:
        df = _buffer_to_df(symbol, tf)
        if df.is_empty() or len(df) < 20:
            continue

        df = _ict_ms.detect_swings(df)
        df = _ict_ms.detect_bos_mss(df)
        df = _ict_fvg.detect_fvgs(df)
        df = _ict_ob.detect_order_blocks(df)
        df = _ict_liquidity.detect_all(df)
        df = _ict_sessions.detect_sessions(df)
        df = _ict_pd.compute_zones(df)
        df = _ict_breaker.detect_breaker_blocks(df)

        mss_type = None
        if "mss" in df.columns:
            latest_mss = df["mss"].drop_nulls().tail(1)
            if len(latest_mss) > 0:
                mss_type = latest_mss[0]
        sweep_type = None
        if "liquidity_sweep_type" in df.columns:
            latest_sweep = df["liquidity_sweep_type"].drop_nulls().tail(1)
            if len(latest_sweep) > 0:
                sweep_type = latest_sweep[0]

        signal = _signal_engine.generate_signal(
            df, mss_type=mss_type, sweep_type=sweep_type,
            news_sentiment=0.0, timeframe=tf,
            htf_bias=htf_bias,
        )
        signal["symbol"] = symbol
        signal["id"] = None

        if "atr" in df.columns:
            latest_atr = df["atr"].tail(1).to_list()
            signal["atr"] = latest_atr[0] if latest_atr and latest_atr[0] is not None else 0.0
        else:
            signal["atr"] = 0.0

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

    if not all_signals:
        return

    _generated_count = len(all_signals)
    if htf_bias != "neutral":
        all_signals = [s for s in all_signals if s.get("htf_aligned", True)]
    else:
        all_signals = []

    _health["total_signals_generated"] = _health.get("total_signals_generated", 0) + _generated_count
    _health["total_signals_kept"] = _health.get("total_signals_kept", 0) + len(all_signals)

    if not all_signals:
        return

    for s in all_signals:
        _signal_id_counter += 1
        s["id"] = _signal_id_counter

    _recent_signals = all_signals + _recent_signals
    if len(_recent_signals) > 500:
        _recent_signals = _recent_signals[:500]

    try:
        current_prices = dict(_latest_prices)
        for s in all_signals:
            sym = s.get("symbol", "")
            live = _latest_prices.get(sym, 0.0)
            if live > 0 and s.get("price", 0) > 0:
                s["trigger_price"] = s["price"]
                s["price"] = live

        _demo_account.process_signals(all_signals, current_prices)

        _recent_trades = _demo_account.get_closed_trades_list(500)
        perf = _demo_account.get_performance()
        perf["open_positions_count"] = len(_demo_account.open_positions)
        open_positions = _demo_account.get_open_positions_list()
        for pos_data in open_positions:
            sym = pos_data["symbol"]
            prec = _price_precision(sym)
            cur_price = _latest_prices.get(sym, 0.0)
            pos_data["current_price"] = round(cur_price, prec) if cur_price > 0 else 0.0
            pos_data["entry_price"] = round(pos_data["entry_price"], prec)
            pos_data["stop_loss"] = round(pos_data["stop_loss"], prec)
            pos_data["take_profit"] = round(pos_data["take_profit"], prec)
            if cur_price > 0 and pos_data["entry_price"] > 0:
                if pos_data["side"] == "LONG":
                    pos_data["unrealized_pnl"] = round((cur_price - pos_data["entry_price"]) * pos_data["quantity"], 2)
                else:
                    pos_data["unrealized_pnl"] = round((pos_data["entry_price"] - cur_price) * pos_data["quantity"], 2)
        perf["open_positions"] = open_positions
        _performance_cache = perf
    except Exception as e:
        logger.warning(f"[Binance] Demo account failed: {e}")

    if discord_bot:
        for s in all_signals:
            stype = s.get("signal_type", "NEUTRAL")
            score_val = s.get("score", 0)
            in_kz = s.get("in_kill_zone", False)
            if score_val >= 70 and in_kz:
                try:
                    await discord_bot.send_signal(s)
                except Exception as e:
                    logger.warning(f"[Binance] Discord send failed: {e}")

    _health["last_cycle_time"] = datetime.utcnow().isoformat() + "Z"
    logger.info(f"[Binance] {symbol} {tf_closed}: {len(all_signals)} signals")


async def _binance_crypto_worker():
    """
    Real-time crypto worker using Binance WebSocket.
    1. Backfills candle buffers from CoinGecko
    2. Connects to Binance WS for 1m/5m/15m klines + ticker
    3. On candle close -> runs ICT analysis immediately
    4. On ticker -> updates _latest_prices
    """
    global _latest_prices, _latest_ticks

    await _backfill_crypto_buffers()

    url = f"{BINANCE_WS_URL}?streams={_binance_streams()}"
    retry_delay = 1.0
    last_tf_analysis: Dict[str, float] = {}

    while True:
        try:
            logger.info("[Binance] Connecting to WebSocket...")
            async with websockets.connect(url, ping_interval=30) as ws:
                logger.info("[Binance] WebSocket connected.")
                retry_delay = 1.0

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    stream_name = msg.get("stream", "")
                    data = msg.get("data", {})
                    event_type = data.get("e", "")

                    if event_type == "kline":
                        k = data.get("k", {})
                        symbol = data.get("s", "")
                        tf = k.get("i", "")
                        is_closed = k.get("x", False)

                        if symbol not in BINANCE_SYMBOLS or tf not in BINANCE_TIMEFRAMES:
                            continue

                        candle = {
                            "timestamp": datetime.fromtimestamp(k["t"] / 1000),
                            "open": float(k["o"]),
                            "high": float(k["h"]),
                            "low": float(k["l"]),
                            "close": float(k["c"]),
                            "volume": float(k["v"]),
                        }
                        _append_to_buffer(symbol, tf, candle)
                        _latest_prices[symbol] = float(k["c"])

                        if is_closed:
                            now = time.time()
                            dedup_key = f"{symbol}_{tf}_{k['t']}"
                            if dedup_key in last_tf_analysis:
                                continue
                            last_tf_analysis[dedup_key] = now
                            if len(last_tf_analysis) > 1000:
                                cutoff = now - 120
                                last_tf_analysis = {k: v for k, v in last_tf_analysis.items() if v > cutoff}

                            logger.info(f"[Binance] {symbol} {tf} closed @ {candle['close']}")
                            await _run_crypto_analysis(symbol, tf)

                    elif event_type == "24hrTicker":
                        symbol = data.get("s", "")
                        if symbol not in BINANCE_SYMBOLS:
                            continue
                        price = float(data.get("c", 0))
                        if price > 0:
                            _latest_prices[symbol] = price
                            _latest_ticks[symbol] = {
                                "symbol": symbol,
                                "price": price,
                                "change_24h": round(float(data.get("P", 0)), 2),
                                "high_24h": float(data.get("h", price)),
                                "low_24h": float(data.get("l", price)),
                                "volume": round(float(data.get("v", 0)), 2),
                                "timestamp": datetime.utcnow().isoformat() + "Z",
                            }

        except websockets.exceptions.WebSocketException as e:
            logger.warning(f"[Binance] WS error: {e}. Reconnecting in {retry_delay:.0f}s...")
        except Exception as e:
            logger.warning(f"[Binance] WS unexpected: {e}. Reconnecting in {retry_delay:.0f}s...")
            _health["last_error_time"] = datetime.utcnow().isoformat() + "Z"
            _health["last_error_message"] = f"Binance WS: {e}"

        await asyncio.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, 60.0)


# ── HTF Bias Worker (replaces old timer-based signal worker) ────────────

async def _htf_bias_worker():
    """
    Periodically fetches 1h data from CoinGecko and updates HTF bias.
    Runs every 15 minutes. The Binance crypto worker reads _health["htf_bias"].
    """
    global _health
    collector = CoinGeckoCollector(symbols=["BTCUSDT"], timeframes=["1h"])

    while True:
        try:
            df_htf = await collector.fetch_historical("BTCUSDT", "1h", 168)
            if not df_htf.is_empty() and len(df_htf) >= 26:
                htf_bias = determine_bias_from_ema(df_htf, fast=12, slow=26, threshold_pct=0.5)
                df_swings = _ict_ms.detect_swings(df_htf)
                swing_bias = determine_bias_from_swings(df_swings)
                logger.info(f"[Bias] HTF: {htf_bias.upper()} (EMA) swings: {swing_bias.upper()}, {len(df_htf)} candles")
                _health["htf_bias"] = htf_bias
                _health["cycle_count"] = _health.get("cycle_count", 0) + 1
            elif not df_htf.is_empty() and len(df_htf) >= 8:
                df_swings = _ict_ms.detect_swings(df_htf)
                htf_bias = determine_bias_from_swings(df_swings)
                _health["htf_bias"] = htf_bias
                logger.info(f"[Bias] HTF: {htf_bias.upper()} (swing fallback, {len(df_htf)} candles)")
            else:
                logger.warning(f"[Bias] Not enough data ({len(df_htf)} candles), keeping current")
        except Exception as e:
            logger.warning(f"[Bias] Update failed: {e}")
            _health["last_error_time"] = datetime.utcnow().isoformat() + "Z"
            _health["last_error_message"] = f"Bias: {e}"

        _health["status"] = "running"
        await asyncio.sleep(900)


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
    data_sources = ["CoinGecko (crypto)"]
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
        "bullish_score": s.get("bullish_score", 0),
        "bearish_score": s.get("bearish_score", 0),
        "net_score": s.get("net_score", 0),
        "price": s.get("price", 0),
        "timeframe": s.get("timeframe", "1h"),
        "bias": s.get("bias", "neutral"),
        "in_kill_zone": s.get("in_kill_zone", False),
        "timestamp": (
            s["timestamp"].isoformat()
            if hasattr(s.get("timestamp"), "isoformat")
            else str(s.get("timestamp", ""))
        ),
        "confidence": s.get("confidence", 0.5),
        "meta_data": {
            "mss": details.get("mss", False),
            "mss_type": details.get("mss_type"),
            "sweep": details.get("sweep", False),
            "sweep_type": details.get("sweep_type"),
            "bullish_fvg": details.get("bullish_fvg", False),
            "bearish_fvg": details.get("bearish_fvg", False),
            "bullish_ob": details.get("bullish_ob", False),
            "bearish_ob": details.get("bearish_ob", False),
            "fvg": details.get("fvg", False) or details.get("bullish_fvg", False) or details.get("bearish_fvg", False),
            "ob": details.get("ob", False) or details.get("bullish_ob", False) or details.get("bearish_ob", False),
            "discount": details.get("discount", False),
            "ote": details.get("ote", False),
            "bias": details.get("bias", "neutral"),
            "news_sentiment": details.get("news_sentiment", 0.0),
            "in_kill_zone": s.get("in_kill_zone", False),
            "htf_bias": s.get("htf_bias", "neutral"),
            "htf_aligned": s.get("htf_aligned", True),
            "active_sessions": details.get("active_sessions", []),
            "active_kill_zones": details.get("active_kill_zones", []),
        },
    }


# ─── Candles (real) ──────────────────────────────────────────────────

@app.get("/candles/{symbol}")
async def get_candles(symbol: str, timeframe: str = "1h", limit: int = 100):
    """
    Fetch historical candles from CoinGecko.
    Supports crypto pairs (BTCUSDT, ETHUSDT). Forex pairs return empty with a note.
    """
    symbol = symbol.upper()

    # Only crypto pairs are available via CoinGecko
    CRYPTO_SYMBOLS = {"BTCUSDT", "ETHUSDT"}

    if symbol not in CRYPTO_SYMBOLS:
        return {
            "error": f"Real data for {symbol} requires a forex API provider",
            "data": [],
        }

    try:
        collector = CoinGeckoCollector(symbols=[symbol], timeframes=[timeframe])
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
    for i, t in enumerate(trades[:limit]):            result_trades.append({
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
            "exit_reason": t.get("exit_reason", ""),
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


# ─── Demo Account (forward-testing) ───────────────────────────────

@app.get("/demo/account")
async def get_demo_account():
    """Return demo account overview — balance, open positions, performance."""
    # The demo_account is created inside _signal_worker, so we access it via
    # the latest performance cache + open positions from the global state.
    # Since _performance_cache is updated by the demo account each cycle, we
    # can enrich it with the account balance and open positions info.
    summary = {
        "balance": _performance_cache.get("capital_remaining", 10000.0)
            if _performance_cache else 10000.0,
        "initial_balance": 10000.0,
        "total_profit": _performance_cache.get("total_profit", 0.0)
            if _performance_cache else 0.0,
        "total_trades": _performance_cache.get("total_trades", 0)
            if _performance_cache else 0,
        "win_rate": _performance_cache.get("win_rate", 0.0)
            if _performance_cache else 0.0,
        "profit_factor": _performance_cache.get("profit_factor", 0.0)
            if _performance_cache else 0.0,
        "max_drawdown": _performance_cache.get("max_drawdown", 0.0)
            if _performance_cache else 0.0,
        "avg_rr": _performance_cache.get("avg_rr", 0.0)
            if _performance_cache else 0.0,
        "total_wins": _performance_cache.get("total_wins", 0)
            if _performance_cache else 0,
        "total_losses": _performance_cache.get("total_losses", 0)
            if _performance_cache else 0,
        "peak_balance": _performance_cache.get("peak_balance", 10000.0)
            if _performance_cache else 10000.0,
        "current_drawdown_pct": _performance_cache.get("current_drawdown_pct", 0.0)
            if _performance_cache else 0.0,
        "open_positions_count": _performance_cache.get("open_positions_count", 0)
            if _performance_cache else 0,
        "open_positions": _performance_cache.get("open_positions", [])
            if _performance_cache else [],
    }
    return summary


# ─── Health / Debug ──────────────────────────────────────────────────

@app.get("/api/health")
async def get_health():
    """
    Return system health status for debugging.
    Exposes HTF bias, last cycle time, error counts, and worker status.
    """
    now = datetime.utcnow().isoformat() + "Z"
    uptime = now
    if _health.get("started_at"):
        started = datetime.fromisoformat(_health["started_at"].replace("Z", ""))
        uptime_secs = (datetime.utcnow() - started).total_seconds()
        uptime = f"{uptime_secs / 60:.0f}m {uptime_secs % 60:.0f}s"

    return {
        "status": _health.get("status", "unknown"),
        "uptime": uptime,
        "started_at": _health.get("started_at"),
        "last_cycle_time": _health.get("last_cycle_time"),
        "cycle_count": _health.get("cycle_count", 0),
        "htf_bias": _health.get("htf_bias", "neutral"),
        "total_signals_generated": _health.get("total_signals_generated", 0),
        "total_signals_kept": _health.get("total_signals_kept", 0),
        "total_trades_executed": _health.get("total_trades_executed", 0),
        "last_error_time": _health.get("last_error_time"),
        "last_error_message": _health.get("last_error_message"),
        "data_sources": _health.get("data_sources", []),
        "btc_price": _latest_prices.get("BTCUSDT", 0),
        "eth_price": _latest_prices.get("ETHUSDT", 0),
        "forex_prices_available": {s: _latest_prices.get(s, 0) for s in FOREX_SYMBOLS},
        "twelve_data_connected": TWELVEDATA_API_KEY and any(s in _latest_ticks for s in FOREX_SYMBOLS),
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

# ── Crypto (via CoinGecko) ──────────────────────────────────────────────
COINGECKO_IDS = "bitcoin,ethereum"

# ── Forex (via Twelve Data) ─────────────────────────────────────────────
FOREX_SYMBOLS = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]

# Twelve Data uses forward-slash format (EUR/USD)
TWELVEDATA_SYMBOL_MAP = {"EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "XAUUSD": "XAU/USD", "USDJPY": "USD/JPY"}
TWELVEDATA_SYMBOLS = list(TWELVEDATA_SYMBOL_MAP.values())  # ["EUR/USD", "GBP/USD", "XAU/USD", "USD/JPY"]
TWELVEDATA_WS_URL = f"wss://ws.twelvedata.com/v1/quotes/price?apikey={TWELVEDATA_API_KEY}"
TWELVEDATA_REST_URL = "https://api.twelvedata.com/quote"

FOREX_BASE_PRICES = {"EURUSD": 1.1042, "GBPUSD": 1.2654, "XAUUSD": 2342.10, "USDJPY": 151.24}  # fallback seed prices (overwritten by Twelve Data)
FOREX_PRECISION = {"EURUSD": 4, "GBPUSD": 4, "XAUUSD": 2, "USDJPY": 3}  # decimal places per symbol

# Default precision for symbols not in FOREX_PRECISION (crypto)
DEFAULT_PRECISION = 2


def _price_precision(symbol: str) -> int:
    """Return appropriate decimal places for a given symbol's price display."""
    return FOREX_PRECISION.get(symbol, DEFAULT_PRECISION)

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

                        # Refresh 24h stats from REST every 15 minutes (free tier rate limits)
                        now = datetime.utcnow()
                        if (now - last_rest_fetch).total_seconds() >= 900:
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


# ── Dashboard static files ────────────────────────────────────────────
from fastapi.staticfiles import StaticFiles
import os as _os

_dashboard_dir = _os.path.join(_os.path.dirname(__file__), "static")
if _os.path.isdir(_dashboard_dir) and _os.path.exists(_os.path.join(_dashboard_dir, "index.html")):
    # Mount the entire static directory at /dashboard — serves assets + index.html with SPA fallback
    app.mount("/dashboard", StaticFiles(directory=_dashboard_dir, html=True), name="dashboard")
    logger.info(f"Dashboard available at /dashboard — {_dashboard_dir}")
else:
    logger.info("No dashboard build found — API-only mode (run 'cd dashboard && npm run build' to enable)")


# ── WebSocket endpoint ────────────────────────────────────────────────

async def _stream_prices(websocket: WebSocket):
    """Stream prices to the connected dashboard client.

    Crypto symbols come from Binance WS ticker (_binance_crypto_worker).
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
