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
# CoinGecko removed — using OKX for all crypto data
from ict_engine.market_structure import MarketStructure
from ict_engine.fvg import FVGDetector
from ict_engine.order_blocks import OrderBlockDetector
from ict_engine.liquidity import LiquidityDetector
from ict_engine.sessions import SessionDetector
from ict_engine.premium_discount import PremiumDiscountDetector
from ict_engine.breaker_block import BreakerBlockDetector
from risk.manager import RiskManager
from discord.bot import DiscordBot
from demo_account import DemoAccount
from signal_engine.engine import SignalEngine, determine_bias_from_swings, determine_bias_from_ema

# ── App state ─────────────────────────────────────────────────────────
_signal_id_counter = 0
_recent_signals: List[Dict] = []
_recent_trades: List[Dict] = []
_performance_cache: Dict = {}

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
    sl_multiplier=1.5,
    reentry_cooldown_minutes=0,
    symbol_sl_multipliers={"BTCUSDT": 0.5, "ETHUSDT": 0.5},
    symbol_min_scores={"BTCUSDT": 70, "ETHUSDT": 70},
)

# ── Binance crypto data ──────────────────────────────────────────────
BINANCE_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
BINANCE_TIMEFRAMES = ["1m", "5m", "15m"]
BINANCE_BUFFER_LIMITS = {"1m": 360, "5m": 288, "15m": 168}  # candles per buffer

# Candle buffers: _candle_buffers[symbol][timeframe] = List[Dict]
_candle_buffers: Dict[str, Dict[str, List[Dict]]] = {}

# ── API credentials ────────────────────────────────────────────────────
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

    # Start crypto data worker (OKX 15s poll + Binance WS attempt)
    crypto_task = asyncio.create_task(_crypto_data_worker())
    _background_tasks.append(crypto_task)
    logger.info("Crypto data worker scheduled (OKX 15s poll + Binance WS attempt).")

    # Start HTF bias worker (OKX 1h data, updates every 15 min)
    bias_task = asyncio.create_task(_htf_bias_worker())
    _background_tasks.append(bias_task)
    logger.info("HTF bias worker scheduled (OKX 1h, 15min cycle).")

    # Health tracking
    _health["data_sources"] = ["OKX (crypto, 15s poll)"]
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

# ── Crypto Data Worker (OKX REST 15s poll + Binance WS attempt) ─────────

def _resample_5m_to_15m(df: pl.DataFrame) -> pl.DataFrame:
    idx = df.with_row_index().with_columns((pl.col("index") // 3).alias("_g"))
    return idx.group_by("_g", maintain_order=True).agg([
        pl.col("timestamp").first(), pl.col("open").first(),
        pl.col("high").max(), pl.col("low").min(),
        pl.col("close").last(), pl.col("volume").sum(),
    ]).drop("_g").sort("timestamp")


async def _backfill_crypto_buffers():
    """Backfill 5m buffers from OKX on startup, resample 15m."""
    global _candle_buffers
    for symbol in BINANCE_SYMBOLS:
        candles = await _okx_fetch_candles(symbol, "5m", 288)
        if candles:
            buf = [{"timestamp": c["timestamp"], "open": c["open"], "high": c["high"],
                    "low": c["low"], "close": c["close"], "volume": c["volume"]}
                   for c in candles]
            _candle_buffers.setdefault(symbol, {})["5m"] = buf
            # Resample to 15m
            df_5m = pl.DataFrame(buf)
            df_15m = _resample_5m_to_15m(df_5m)
            buf15 = [{"timestamp": r["timestamp"], "open": r["open"], "high": r["high"],
                      "low": r["low"], "close": r["close"], "volume": r["volume"]}
                     for r in df_15m.to_dicts()]
            _candle_buffers[symbol]["15m"] = buf15
            logger.info(f"[Crypto] Backfilled {len(buf)} 5m + {len(buf15)} 15m for {symbol}")
        else:
            logger.warning(f"[Crypto] OKX backfill failed for {symbol}, starting empty")
            _candle_buffers.setdefault(symbol, {}).setdefault("5m", [])
            _candle_buffers.setdefault(symbol, {}).setdefault("15m", [])


def _buffer_to_df(symbol: str, tf: str) -> pl.DataFrame:
    buf = _candle_buffers.get(symbol, {}).get(tf, [])
    if len(buf) < 10:
        return pl.DataFrame()
    return pl.DataFrame(buf)


def _append_to_buffer(symbol: str, tf: str, candle: Dict):
    buf = _candle_buffers.setdefault(symbol, {}).setdefault(tf, [])
    if buf and buf[-1]["timestamp"] == candle["timestamp"]:
        buf[-1] = candle
    else:
        buf.append(candle)
    limit = BINANCE_BUFFER_LIMITS.get(tf, 288)
    if len(buf) > limit:
        buf[:] = buf[-limit:]


async def _run_crypto_analysis(symbol: str, tf_closed: str):
    """
    Called when a new 5m candle closes (from OKX 15s polling or Binance WS).
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
            timeframe=tf,
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
        logger.warning(f"[Crypto] Demo account failed: {e}")

    # Only send Discord alerts for signals that will actually open a new position
    # Skip if we already have an open position for that symbol
    if discord_bot:
        for s in all_signals:
            symbol = s.get("symbol", "")
            stype = s.get("signal_type", "NEUTRAL")
            score_val = s.get("score", 0)
            in_kz = s.get("in_kill_zone", False)
            if score_val >= 80 and in_kz:
                if symbol in _demo_account.open_positions:
                    logger.info(f"[Discord] Skipping {symbol} {stype} — position already open")
                    continue
                try:
                    await discord_bot.send_signal(s)
                except Exception as e:
                    logger.warning(f"[Crypto] Discord send failed: {e}")

    _health["last_cycle_time"] = datetime.utcnow().isoformat() + "Z"
    logger.info(f"[Crypto] {symbol} {tf_closed}: {len(all_signals)} signals")


# ── OKX symbol map ────────────────────────────────────────────────────
OKX_SYMBOL_MAP = {"BTCUSDT": "BTC-USDT", "ETHUSDT": "ETH-USDT"}


async def _okx_fetch_candles(symbol: str, bar: str, limit: int = 288) -> Optional[List[Dict]]:
    """Fetch OHLCV candles from OKX REST API.

    OKX returns candles with a 'confirm' field: "0" = still forming, "1" = closed.
    Returns newest-first, we reverse to oldest-first. No API key needed for public data.
    """
    inst_id = OKX_SYMBOL_MAP.get(symbol)
    if not inst_id:
        return None
    url = "https://www.okx.com/api/v5/market/candles"
    params = {"instId": inst_id, "bar": bar, "limit": str(limit)}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning(f"[OKX] HTTP {resp.status_code} for {symbol} {bar}")
                return None
            data = resp.json()
            if data.get("code") != "0":
                return None
            candles = data.get("data", [])
            # Reverse: OKX returns newest-first, we want oldest-first
            result = []
            for c in reversed(candles):
                result.append({
                    "timestamp": datetime.fromtimestamp(int(c[0]) / 1000),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                    "confirmed": c[8] == "1",
                })
            return result
    except Exception as e:
        logger.warning(f"[OKX] Fetch failed for {symbol} {bar}: {e}")
        return None


async def _crypto_data_worker():
    """
    Crypto data worker: primary source is OKX REST API (15s polling, no API key needed).
    Also attempts Binance WebSocket as a bonus (may not work from cloud IPs).
    """
    global _latest_prices, _latest_ticks

    await _backfill_crypto_buffers()
    _last_ts: Dict[str, datetime] = {}  # track last confirmed candle timestamp

    # Background Binance WS attempt (may or may not work from cloud IPs)
    BINANCE_WS_URL = "wss://stream.binance.com:9443/stream"
    streams = "/".join([f"{s.lower()}@kline_5m/{s.lower()}@kline_15m/{s.lower()}@ticker" for s in BINANCE_SYMBOLS])

    async def _try_ws():
        retry = 1.0
        while True:
            try:
                async with websockets.connect(f"{BINANCE_WS_URL}?streams={streams}", ping_interval=30, open_timeout=10) as ws:
                    logger.info("[Crypto] Binance WS connected.")
                    retry = 1.0
                    async for raw in ws:
                        msg = json.loads(raw)
                        data = msg.get("data", {})
                        etype = data.get("e", "")
                        if etype == "kline":
                            k = data.get("k", {})
                            sym = data.get("s", "")
                            tf = k.get("i", "")
                            if sym not in BINANCE_SYMBOLS or tf not in ["5m", "15m"]:
                                continue
                            candle = {"timestamp": datetime.fromtimestamp(k["t"]/1000),
                                      "open": float(k["o"]), "high": float(k["h"]),
                                      "low": float(k["l"]), "close": float(k["c"]),
                                      "volume": float(k["v"])}
                            _append_to_buffer(sym, tf, candle)
                            _latest_prices[sym] = float(k["c"])
                            if k.get("x", False):
                                logger.info(f"[Crypto] WS {sym} {tf} closed @ {candle['close']}")
                                await _run_crypto_analysis(sym, tf)
                        elif etype == "24hrTicker":
                            sym = data.get("s", "")
                            if sym not in BINANCE_SYMBOLS:
                                continue
                            p = float(data.get("c", 0))
                            if p > 0:
                                _latest_prices[sym] = p
                                _latest_ticks[sym] = {"symbol": sym, "price": p,
                                    "change_24h": round(float(data.get("P", 0)), 2),
                                    "high_24h": float(data.get("h", p)),
                                    "low_24h": float(data.get("l", p)),
                                    "volume": round(float(data.get("v", 0)), 2),
                                    "timestamp": datetime.utcnow().isoformat() + "Z"}
            except Exception:
                pass  # WS unavailable (e.g. HTTP 451), keep retrying
            await asyncio.sleep(retry)
            retry = min(retry * 2, 120.0)

    asyncio.create_task(_try_ws())

    # Main data loop: poll OKX every 15s
    while True:
        try:
            await asyncio.sleep(15)

            for symbol in BINANCE_SYMBOLS:
                candles = await _okx_fetch_candles(symbol, "5m", 288)
                if not candles:
                    logger.warning(f"[Crypto] OKX fetch failed for {symbol}, skipping...")
                    continue

                # Reverse so newest is last
                candles_sorted = sorted(candles, key=lambda c: c["timestamp"])
                last = candles_sorted[-1]
                _latest_prices[symbol] = last["close"]

                # Only process when a new confirmed (closed) candle appears
                confirmed = [c for c in candles_sorted if c.get("confirmed", True)]
                if not confirmed:
                    continue
                last_confirmed = confirmed[-1]["timestamp"]
                if last_confirmed != _last_ts.get(symbol):
                    _last_ts[symbol] = last_confirmed
                    # Update buffers
                    _candle_buffers.setdefault(symbol, {})["5m"] = [
                        {"timestamp": c["timestamp"], "open": c["open"],
                         "high": c["high"], "low": c["low"], "close": c["close"],
                         "volume": c["volume"]} for c in candles_sorted
                    ]
                    # Resample to 15m
                    df_5m = pl.DataFrame(_candle_buffers[symbol]["5m"])
                    df_15m = _resample_5m_to_15m(df_5m)
                    _candle_buffers[symbol]["15m"] = [
                        {"timestamp": r["timestamp"], "open": r["open"],
                         "high": r["high"], "low": r["low"], "close": r["close"],
                         "volume": r["volume"]} for r in df_15m.to_dicts()
                    ]
                    # Update tick
                    _latest_ticks[symbol] = {"symbol": symbol, "price": last["close"],
                        "change_24h": 0.0, "high_24h": last["high"],
                        "low_24h": last["low"], "volume": round(last["volume"], 2),
                        "timestamp": datetime.utcnow().isoformat() + "Z"}
                    # Run analysis
                    logger.info(f"[Crypto] {symbol} 5m: new candle @ {last['close']}")
                    await _run_crypto_analysis(symbol, "5m")

        except Exception as e:
            logger.warning(f"[Crypto] Polling error: {e}")
            _health["last_error_time"] = datetime.utcnow().isoformat() + "Z"
            _health["last_error_message"] = f"Crypto: {e}"


# ── HTF Bias Worker (replaces old timer-based signal worker) ────────────

async def _htf_bias_worker():
    """
    Periodically fetches 1h data from OKX and updates HTF bias via EMA.
    Runs every 15 minutes. The crypto data worker reads _health["htf_bias"].
    """
    global _health

    while True:
        try:
            candles = await _okx_fetch_candles("BTCUSDT", "1H", 168)
            if candles and len(candles) >= 26:
                df_htf = pl.DataFrame(candles)
                htf_bias = determine_bias_from_ema(df_htf, fast=12, slow=26, threshold_pct=0.5)
                df_swings = _ict_ms.detect_swings(df_htf)
                swing_bias = determine_bias_from_swings(df_swings)
                logger.info(f"[Bias] HTF: {htf_bias.upper()} (EMA) swings: {swing_bias.upper()}, {len(candles)} candles")
                _health["htf_bias"] = htf_bias
                _health["cycle_count"] = _health.get("cycle_count", 0) + 1
            elif candles and len(candles) >= 8:
                df_htf = pl.DataFrame(candles)
                df_swings = _ict_ms.detect_swings(df_htf)
                htf_bias = determine_bias_from_swings(df_swings)
                _health["htf_bias"] = htf_bias
                logger.info(f"[Bias] HTF: {htf_bias.upper()} (swing fallback, {len(candles)} candles)")
            else:
                logger.warning(f"[Bias] Not enough data ({len(candles) if candles else 0} candles), keeping current")
        except Exception as e:
            logger.warning(f"[Bias] Update failed: {e}")
            _health["last_error_time"] = datetime.utcnow().isoformat() + "Z"
            _health["last_error_message"] = f"Bias: {e}"

        _health["status"] = "running"
        await asyncio.sleep(900)



# ─── Root ───────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "status": "online",
        "version": "0.1.0",
        "data_source": "OKX (crypto, 15s poll)",
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
    Fetch historical candles from OKX REST API.
    Supports crypto pairs (BTCUSDT, ETHUSDT).
    """
    symbol = symbol.upper()

    CRYPTO_SYMBOLS = {"BTCUSDT", "ETHUSDT"}

    if symbol not in CRYPTO_SYMBOLS:
        return {
            "error": f"Unsupported symbol: {symbol}. Only BTCUSDT and ETHUSDT are available.",
            "data": [],
        }

    try:
        tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}
        bar = tf_map.get(timeframe, "1H")
        candles = await _okx_fetch_candles(symbol, bar, limit)

        if not candles:
            return []

        return [
            {
                "id": i + 1,
                "symbol": symbol,
                "timeframe": timeframe,
                "timestamp": c["timestamp"].isoformat()
                if hasattr(c["timestamp"], "isoformat")
                else str(c["timestamp"]),
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c["volume"],
            }
            for i, c in enumerate(candles)
        ]

    except Exception as e:
        logger.error(f"Candle fetch failed for {symbol}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch candles: {e}")


# ─── Backtest data (paginated OKX history) ────────────────────────────

OKX_BAR_CAPACITY: Dict[str, int] = {"1m": 720, "5m": 288, "15m": 96, "1H": 24, "4H": 6, "1D": 1}  # approx candles per day


async def _okx_fetch_history(symbol: str, bar: str, limit: int = 100, after: Optional[datetime] = None) -> Optional[List[Dict]]:
    """Fetch historical candles from OKX history-candles endpoint (up to 100 per call)."""
    inst_id = OKX_SYMBOL_MAP.get(symbol)
    if not inst_id:
        return None
    url = "https://www.okx.com/api/v5/market/history-candles"
    params = {"instId": inst_id, "bar": bar, "limit": str(min(limit, 100))}
    if after:
        params["after"] = str(int(after.timestamp() * 1000))
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning(f"[OKX] History HTTP {resp.status_code} for {symbol} {bar}")
                return None
            data = resp.json()
            if data.get("code") != "0":
                logger.warning(f"[OKX] History API error {data.get('code')} for {symbol} {bar}")
                return None
            candles = data.get("data", [])
            result = []
            for c in reversed(candles):
                result.append({
                    "timestamp": datetime.fromtimestamp(int(c[0]) / 1000),
                    "open": float(c[1]), "high": float(c[2]),
                    "low": float(c[3]), "close": float(c[4]),
                    "volume": float(c[5]),
                })
            return result
    except Exception as e:
        logger.warning(f"[OKX] History fetch failed: {e}")
        return None


@app.get("/backtest-data/{symbol}")
async def get_backtest_data(
    symbol: str,
    days: int = Query(30, ge=1, le=90),
    bar: str = Query("5m", regex="^(1m|5m|15m|1H|4H|1D)$"),
    before: Optional[str] = Query(None, description="ISO timestamp to end the window (default: now)"),
):
    """
    Fetch many days of historical OHLCV data for backtesting.
    Paginates OKX's history-candles endpoint server-side.
    Returns candles oldest-first, no API key needed.

    Optionally specify `before` (ISO date string like "2025-06-15") to
    fetch data ending at that date instead of the current time.
    """
    symbol = symbol.upper()
    if symbol not in {"BTCUSDT", "ETHUSDT"}:
        raise HTTPException(status_code=400, detail=f"Unsupported symbol: {symbol}")

    try:
        per_day = OKX_BAR_CAPACITY.get(bar, 288)
        total_needed = days * per_day
        all_candles: List[Dict] = []
        # Start from the `before` timestamp if provided, otherwise newest
        after_ts = None
        if before:
            before_ts = before.replace("Z", "+00:00") if isinstance(before, str) else before
            after_ts = datetime.fromisoformat(before_ts)

        while len(all_candles) < total_needed:
            batch = await _okx_fetch_history(symbol, bar, 100, after=after_ts)
            if not batch or len(batch) == 0:
                break
            # Add oldest-first (batch is already reversed)
            all_candles.extend(batch)
            # Set after_ts to oldest candle in this batch for next page
            after_ts = batch[0]["timestamp"]
            await asyncio.sleep(0.15)  # rate limit courtesy

        if not all_candles:
            return []

        # Dedup by timestamp
        seen = set()
        deduped = []
        for c in all_candles:
            key = c["timestamp"].timestamp()
            if key not in seen:
                seen.add(key)
                deduped.append(c)

        # Final oldest-first sort, trim to exact requested count
        deduped.sort(key=lambda c: c["timestamp"])
        deduped = deduped[:total_needed]

        logger.info(f"[Backtest] Fetched {len(deduped)} {bar} candles for {symbol} ({days}d)")

        return [
            {
                "id": i + 1,
                "symbol": symbol,
                "timeframe": bar,
                "timestamp": c["timestamp"].isoformat()
                if hasattr(c["timestamp"], "isoformat")
                else str(c["timestamp"]),
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c["volume"],
            }
            for i, c in enumerate(deduped)
        ]

    except Exception as e:
        logger.error(f"[Backtest] Fetch failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch backtest data: {e}")


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

# Symbols tracked in the price stream
TRACKED_SYMBOLS = ["BTCUSDT", "ETHUSDT"]

DEFAULT_PRECISION = 2


def _price_precision(symbol: str) -> int:
    """Return appropriate decimal places for a given symbol's price display."""
    return DEFAULT_PRECISION

# Shared in-memory state: latest price for each symbol
_latest_prices: Dict[str, float] = {
    "BTCUSDT": 68420.0, "ETHUSDT": 3520.0,
}
_latest_ticks: Dict[str, Dict] = {}


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

    Crypto prices come from OKX polling.
    """
    await websocket.accept()

    # Send the most recent known prices immediately
    for symbol in TRACKED_SYMBOLS:
        if symbol in _latest_ticks and _latest_ticks[symbol]:
            await websocket.send_json(_latest_ticks[symbol])

    try:
        while True:
            for symbol in TRACKED_SYMBOLS:
                if symbol in _latest_ticks:
                    await websocket.send_json(_latest_ticks[symbol])
                await asyncio.sleep(0.25)
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@app.websocket("/ws/prices")
async def ws_price_stream(websocket: WebSocket):
    await _stream_prices(websocket)
