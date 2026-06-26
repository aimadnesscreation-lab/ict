"""
FastAPI server — ICT Trading Intelligence Platform.

Data Source: Binance REST API only (no OKX).
Orchestration: TradingOrchestrator — unified signal/DemoAccount/exchange/Discord pipeline.
"""

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Optional
from datetime import datetime, timezone
import os
import asyncio
import json
import httpx
import polars as pl
from loguru import logger
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

# ── Imports ──────────────────────────────────────────────────────────
from ict_engine.market_structure import MarketStructure
from signal_engine.engine import determine_bias_from_ema, determine_bias_from_swings
from discord.bot import DiscordBot
from demo_account import DemoAccount
from execution.executor import LiveExecutor
from trading_engine.orchestrator import TradingOrchestrator
from database.manager import DatabaseManager

# ── Database ─────────────────────────────────────────────────────────
_db = DatabaseManager()

# ── App state ────────────────────────────────────────────────────────
_recent_signals: List[Dict] = []

# Risk Settings
MAX_RISK_PER_TRADE_PCT = 1.0
MAX_DAILY_LOSS_PCT = 3.0
MAX_OPEN_POSITIONS = 3
DEMO_INITIAL_BALANCE = float(os.getenv("DEMO_INITIAL_BALANCE", "5000"))

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
    "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "data_sources": ["Binance (WebSockets, Real-time)"],
    "sync_stats": {
        "total_cycles": 0, "total_closed_from_sl": 0, "total_closed_from_tp": 0,
        "total_closed_from_manual": 0, "total_errors": 0,
        "last_sync_time": None, "last_sync_result": None,
    },
}

_demo_account = DemoAccount(
    initial_balance=DEMO_INITIAL_BALANCE, risk_per_trade_pct=MAX_RISK_PER_TRADE_PCT,
    max_daily_loss_pct=MAX_DAILY_LOSS_PCT,
    max_open_positions=MAX_OPEN_POSITIONS,
    sl_multiplier=3.0,  # Combo 521: 3.0x ATR for SL (reduces loss severity vs 1.5x per 5-year optimizer)
    reentry_cooldown_minutes=0,
    symbol_min_scores={"ETHUSDT": 0, "SOLUSDT": 0},  # Combo 521: bypass scoring, uses pattern detection
    spot_only=False,  # Binance Futures — supports both LONG and SHORT
    db_manager=_db,
    tp_ratio=3.0,  # Combo 521: 3R take profit
)

_live_executor = LiveExecutor(mode=os.getenv("EXCHANGE_MODE", "demo"))

# Discord bot
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
_discord_bot: Optional[DiscordBot] = None
if DISCORD_WEBHOOK_URL:
    try:
        _discord_bot = DiscordBot(webhook_url=DISCORD_WEBHOOK_URL)
        logger.info("Discord bot initialized.")
    except Exception as e:
        logger.warning(f"Failed to initialize Discord bot: {e}")

# ── Trading Orchestrator ─────────────────────────────────────────────
_orchestrator = TradingOrchestrator(
    demo_account=_demo_account,
    live_executor=_live_executor,
    discord_bot=_discord_bot,
    kill_zones_enabled=False,  # ETH-only optimal config: trade all sessions
)

# ── ICT detectors for HTF bias ───────────────────────────────────────
_ict_ms = MarketStructure(n=2)

# ── Binance data ─────────────────────────────────────────────────────
SYMBOLS = ["ETHUSDT", "SOLUSDT"]
_candle_buffers: Dict[str, Dict[str, List[Dict]]] = {}
_background_tasks: List[asyncio.Task] = []

# ── Price state (seeded immediately so the dashboard always shows data) ──
_latest_prices: Dict[str, float] = {"ETHUSDT": 1800.0, "SOLUSDT": 140.0}
_NOW = datetime.now(timezone.utc)
_latest_ticks: Dict[str, Dict] = {
    "ETHUSDT": {
        "symbol": "ETHUSDT", "price": 1800.0, "change_24h": 0.0,
        "high_24h": 1800.0, "low_24h": 1800.0, "volume": 0.0,
        "timestamp": _NOW.isoformat().replace("+00:00", "Z"),
    },
    "SOLUSDT": {
        "symbol": "SOLUSDT", "price": 140.0, "change_24h": 0.0,
        "high_24h": 140.0, "low_24h": 140.0, "volume": 0.0,
        "timestamp": _NOW.isoformat().replace("+00:00", "Z"),
    },
}

# ── WebSocket broadcast manager ────────────────────────────────────────
_ws_clients: set[WebSocket] = set()


def _serialize_for_ws(obj: object) -> object:
    """Recursively convert datetimes / non-serializable types to strings."""
    import dataclasses
    if isinstance(obj, datetime):
        return obj.isoformat().replace("+00:00", "Z")
    if dataclasses.is_dataclass(obj):
        return {k: _serialize_for_ws(v) for k, v in dataclasses.asdict(obj).items()}  # type: ignore[arg-type]
    if isinstance(obj, dict):
        return {k: _serialize_for_ws(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_for_ws(v) for v in obj]
    return obj


def _build_ws_payload() -> dict:
    """Build a snapshot of all current state for WS clients."""
    # Signals
    signals = [format_signal(s) for s in _recent_signals[:50]] if _recent_signals else []

    # Trades — always read fresh from DemoAccount
    trades_raw = _demo_account.get_closed_trades_list(200)
    trades = []
    for i, t in enumerate(trades_raw):
        trades.append({
            "id": i + 1, "symbol": t.get("symbol", "ETHUSDT"),
            "signal_type": t.get("signal_type", "NEUTRAL"),
            "entry_time": _serialize_for_ws(t.get("entry_time", "")),
            "exit_time": _serialize_for_ws(t.get("exit_time", "")),
            "entry_price": t.get("entry_price", 0),
            "exit_price": t.get("exit_price", 0),
            "profit": t.get("profit", 0),
            "rr": t.get("rr", 0),
            "result": t.get("result", "BREAK_EVEN"),
            "exit_reason": t.get("exit_reason", ""),
        })

    # Demo account — always read fresh from DemoAccount
    perf = _demo_account.get_performance()
    open_positions = DemoAccount.enrich_positions(
        _demo_account.get_open_positions_list(), dict(_latest_prices),
    )

    demo_account = {
        "balance": perf.get("capital_remaining", DEMO_INITIAL_BALANCE),
        "initial_balance": DEMO_INITIAL_BALANCE,
        "total_profit": perf.get("total_profit", 0.0),
        "total_trades": perf.get("total_trades", 0),
        "win_rate": perf.get("win_rate", 0.0),
        "profit_factor": perf.get("profit_factor", 0.0),
        "max_drawdown": perf.get("max_drawdown", 0.0),
        "avg_rr": perf.get("avg_rr", 0.0),
        "total_wins": perf.get("total_wins", 0),
        "total_losses": perf.get("total_losses", 0),
        "peak_balance": perf.get("peak_balance", DEMO_INITIAL_BALANCE),
        "current_drawdown_pct": perf.get("current_drawdown_pct", 0.0),
        "open_positions_count": len(open_positions),
        "open_positions": _serialize_for_ws(open_positions),
    }

    # Health
    health = _health.copy()
    health["htf_bias"] = _health.get("htf_bias", "neutral")
    health["eth_price"] = _latest_prices.get("ETHUSDT", 0)

    # Risk status
    risk_status = {
        "max_risk_per_trade_pct": MAX_RISK_PER_TRADE_PCT,
        "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
        "max_weekly_loss_pct": 6.0,
        "max_open_positions": MAX_OPEN_POSITIONS,
        "current_daily_loss_pct": round(
            _demo_account.daily_loss
            / (DEMO_INITIAL_BALANCE * MAX_DAILY_LOSS_PCT / 100)
            * MAX_DAILY_LOSS_PCT
            if MAX_DAILY_LOSS_PCT > 0 else 0, 2
        ),
        "current_weekly_loss_pct": 0.0,
        "open_positions_count": len(_demo_account.open_positions),
        "account_balance": _demo_account.balance,
    }

    # Performance metrics
    performance = {
        "win_rate": perf.get("win_rate", 0.0),
        "total_pnl": perf.get("total_profit", 0.0),
        "profit_factor": perf.get("profit_factor", 0.0),
        "max_drawdown": perf.get("max_drawdown", 0.0),
        "sharpe_ratio": perf.get("sharpe_ratio", 0.0),
        "total_trades": perf.get("total_trades", 0),
        "avg_rr": perf.get("avg_rr", 0.0),
    }

    return {
        "type": "snapshot",
        "signals": signals,
        "trades": trades,
        "demo_account": demo_account,
        "health": health,
        "risk_status": risk_status,
        "performance": performance,
    }


async def _broadcast_data():
    """Send current state snapshot to all connected WebSocket clients."""
    if not _ws_clients:
        return
    payload = _build_ws_payload()
    stale: list[WebSocket] = []
    for ws in _ws_clients:
        try:
            await ws.send_json(payload)
        except Exception:
            stale.append(ws)
    for ws in stale:
        _ws_clients.discard(ws)


# ── Lifespan ─────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background workers on startup, cancel on shutdown."""
    # Initialize Database
    await _db.init_db()
    logger.info("Database initialized.")

    # ── State Recovery ───────────────────────────────────────────────
    try:
        last_state = await _db.load_last_state()
        db_positions = await _db.load_positions()
        db_trades = await _db.get_recent_trades(limit=500)
        
        if last_state:
            _demo_account.restore_state(
                balance=last_state['balance'],
                peak_balance=last_state['peak_balance'],
                positions=db_positions,
                trades=db_trades
            )
    except Exception as e:
        logger.error(f"Failed to restore state from DB: {e}")

    # Crypto data worker (Binance WebSockets, Real-time)
    crypto_task = asyncio.create_task(_crypto_data_worker())
    _background_tasks.append(crypto_task)
    logger.info("Crypto data worker started (Binance WebSockets, Real-time).")

    # HTF bias worker (Binance 1h WebSockets, Real-time)
    bias_task = asyncio.create_task(_htf_bias_worker())
    _background_tasks.append(bias_task)
    logger.info("HTF bias worker started (Binance 1h WebSockets, Real-time).")

    # Exchange sync worker (reconciles every 30s)
    if _live_executor and _live_executor.exchange:
        sync_task = asyncio.create_task(_sync_worker())
        _background_tasks.append(sync_task)
        logger.info("Exchange sync worker started (30s cycle).")
    else:
        logger.info("Exchange sync worker not started — no exchange credentials.")

    _health["status"] = "running"
    logger.info(f"Started {len(_background_tasks)} background workers.")
    yield

    for t in _background_tasks:
        t.cancel()
    await asyncio.gather(*_background_tasks, return_exceptions=True)
    _background_tasks.clear()
    logger.info("All background workers stopped.")


app = FastAPI(
    title="ICT Trading Intelligence Platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Binance REST API ─────────────────────────────────────────────────

BINANCE_BAR_MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}


async def _binance_fetch_candles(symbol: str, bar: str, limit: int = 288) -> Optional[List[Dict]]:
    """Fetch OHLCV candles from Binance public REST API.
    No API key needed. Returns oldest-first. Always confirmed candles.
    """
    interval = BINANCE_BAR_MAP.get(bar)
    if not interval:
        return None
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": str(limit)}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.debug(f"[Binance] HTTP {resp.status_code} for {symbol} {bar}")
                return None
            klines = resp.json()
            if not isinstance(klines, list) or len(klines) == 0:
                return None
            result = []
            for k in klines:
                result.append({
                    "timestamp": datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc).replace(tzinfo=None),
                    "open": float(k[1]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4]),
                    "volume": float(k[5]),
                    "confirmed": True,
                })
            return result
    except Exception as e:
        logger.debug(f"[Binance] Fetch failed for {symbol} {bar}: {e}")
        return None


def _resample_5m_to_15m(df: pl.DataFrame) -> pl.DataFrame:
    """Resample 5m candles to 15m using timestamp-based grouping."""
    if df.is_empty():
        return df
    return df.group_by_dynamic(
        "timestamp", 
        every="15m", 
        closed="left",
        label="left"
    ).agg([
        pl.col("open").first(),
        pl.col("high").max(),
        pl.col("low").min(),
        pl.col("close").last(),
        pl.col("volume").sum(),
    ]).sort("timestamp")


async def _backfill_buffers():
    """Backfill 5m buffers on startup, resample 15m."""
    global _candle_buffers
    for symbol in SYMBOLS:
        # Fetch 1000 candles to ensure accurate PDH/PDL and HTF metrics
        candles = await _binance_fetch_candles(symbol, "5m", 1000)
        if candles:
            buf = [{"timestamp": c["timestamp"], "open": c["open"], "high": c["high"],
                    "low": c["low"], "close": c["close"], "volume": c["volume"]}
                   for c in candles]
            _candle_buffers.setdefault(symbol, {})["5m"] = buf
            df_5m = pl.DataFrame(buf)
            df_15m = _resample_5m_to_15m(df_5m)
            buf15 = [{"timestamp": r["timestamp"], "open": r["open"], "high": r["high"],
                      "low": r["low"], "close": r["close"], "volume": r["volume"]}
                     for r in df_15m.to_dicts()]
            _candle_buffers[symbol]["15m"] = buf15
            logger.info(f"[Crypto] Backfilled {len(buf)} 5m + {len(buf15)} 15m for {symbol}")
        else:
            logger.warning(f"[Crypto] Data backfill failed for {symbol}, starting empty")
            _candle_buffers.setdefault(symbol, {}).setdefault("5m", [])
            _candle_buffers.setdefault(symbol, {}).setdefault("15m", [])


# ── Background Workers ───────────────────────────────────────────────

async def _crypto_data_worker():
    """
    Uses Binance WebSockets (via CCXT Pro) for real-time ticker + candles.
    On new candle close: runs orchestrator.process_candle_close().
    """
    global _latest_prices, _latest_ticks, _recent_signals

    await _backfill_buffers()
    
    import ccxt.pro as ccxtpro
    # Initialize CCXT Pro exchange for real-time data
    exchange = ccxtpro.binanceusdm({
        "enableRateLimit": True,
    })
    
    # Track the last processed candle timestamp per symbol
    last_processed_ts: Dict[str, int] = {}
    for symbol in SYMBOLS:
        buf = _candle_buffers.get(symbol, {}).get("5m", [])
        if buf:
            # Convert to ms timestamp for comparison
            last_processed_ts[symbol] = int(buf[-1]["timestamp"].replace(tzinfo=timezone.utc).timestamp() * 1000)

    async def _on_candle_close(symbol: str, source_label: str):
        """
        Shared handler called when a new 5m candle close is detected
        (from either WS or REST). Resamples, runs orchestrator, persists state.
        """
        nonlocal last_processed_ts
        df_5m = pl.DataFrame(_candle_buffers[symbol]["5m"])
        df_15m = _resample_5m_to_15m(df_5m)
        _candle_buffers[symbol]["15m"] = [
            {"timestamp": r["timestamp"], "open": r["open"],
             "high": r["high"], "low": r["low"], "close": r["close"],
             "volume": r["volume"]} for r in df_15m.to_dicts()
        ]

        htf_bias = _health.get("htf_bias", "neutral")
        result = await _orchestrator.process_candle_close(
            symbol=symbol,
            df_5m=df_5m.slice(0, len(df_5m) - 1),
            df_15m=df_15m,
            current_prices=dict(_latest_prices),
            htf_bias=htf_bias,
        )

        for sig in result.get("signals", []):
            db_sig = sig.copy()
            ts = db_sig.get("timestamp")
            if isinstance(ts, datetime):
                db_sig["timestamp"] = ts.replace(tzinfo=None)
            asyncio.ensure_future(_db.save_signal(db_sig))

        global _recent_signals
        _recent_signals = result.get("signals", []) + _recent_signals
        if len(_recent_signals) > 500:
            _recent_signals = _recent_signals[:500]

        perf = result.get("performance", {})
        asyncio.ensure_future(_db.update_account_state(
            balance=perf.get("capital_remaining", 0),
            equity=perf.get("equity", perf.get("capital_remaining", 0)),
            peak_balance=perf.get("peak_balance", 0)
        ))

        _health["total_signals_generated"] = _orchestrator.total_signals_generated
        _health["total_signals_kept"] = _orchestrator.total_signals_kept
        _health["total_trades_executed"] = _orchestrator.total_trades_executed
        _health["last_cycle_time"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _health["cycle_count"] = _orchestrator.cycle_count

        asyncio.ensure_future(_broadcast_data())

    async def handle_tickers():
        """Watch real-time price ticks for all symbols.
        Uses WS; falls back to REST polling every 5s if WS fails."""
        ticker_ws_retries = 0
        ticker_rest_fallback = False
        while True:
            try:
                if not ticker_rest_fallback:
                    try:
                        tickers = await asyncio.wait_for(
                            exchange.watch_tickers(SYMBOLS),
                            timeout=30,
                        )
                        for unified_symbol, t in tickers.items():
                            # CCXT unified format for binanceusdm: "ETH/USDT:USDT"
                            # Strip the settlement suffix after ":", remove "/", uppercase
                            raw = unified_symbol.split(":")[0].replace("/", "").upper()
                            if raw in SYMBOLS:
                                price = float(t["last"])
                                _latest_prices[raw] = price
                                _latest_ticks[raw] = {
                                    "symbol": raw,
                                    "price": price,
                                    "change_24h": round(float(t.get("percentage", 0) or 0), 2),
                                    "high_24h": float(t.get("high", price) or price),
                                    "low_24h": float(t.get("low", price) or price),
                                    "volume": round(float(t.get("baseVolume", 0) or 0), 2),
                                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                                }
                        ticker_ws_retries = 0
                    except asyncio.TimeoutError:
                        ticker_ws_retries += 1
                        if ticker_ws_retries >= 2:
                            ticker_rest_fallback = True
                        else:
                            await asyncio.sleep(2)
                    except Exception as e:
                        logger.debug(f"[WS] Ticker error: {e}")
                        ticker_ws_retries += 1
                        if ticker_ws_retries >= 3:
                            ticker_rest_fallback = True
                        else:
                            await asyncio.sleep(2)
                else:
                    # REST fallback: poll 24hr ticker every 5 seconds
                    for sym in SYMBOLS:
                        try:
                            async with httpx.AsyncClient(timeout=5.0) as client:
                                resp = await client.get(
                                    f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={sym}"
                                )
                                if resp.status_code == 200:
                                    t = resp.json()
                                    price = float(t["lastPrice"])
                                    _latest_prices[sym] = price
                                    _latest_ticks[sym] = {
                                        "symbol": sym,
                                        "price": price,
                                        "change_24h": round(float(t.get("priceChangePercent", 0) or 0), 2),
                                        "high_24h": float(t.get("highPrice", price) or price),
                                        "low_24h": float(t.get("lowPrice", price) or price),
                                        "volume": round(float(t.get("volume", 0) or 0), 2),
                                        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                                    }
                        except Exception:
                            pass
                    # Try to reconnect WS every ~30s
                    ticker_ws_retries += 1
                    if ticker_ws_retries >= 6:
                        logger.info("[WS] Attempting ticker WS reconnect...")
                        ticker_rest_fallback = False
                        ticker_ws_retries = 0
                    await asyncio.sleep(5)
            except Exception as e:
                logger.debug(f"[WS] Ticker loop error: {e}")
                await asyncio.sleep(2)

    async def handle_ohlcv(symbol: str):
        """Watch real-time OHLCV candles and detect closes.
        Uses WS; falls back to REST polling every 60s if WS fails."""
        global _recent_signals
        ohlcv_ws_retries = 0
        ohlcv_rest_fallback = False

        async def _process_candle_close_rest():
            """Fetch 5m candles via REST, detect close, run orchestrator."""
            nonlocal last_processed_ts
            # Fetch 1000 candles to ensure accurate PDH/PDL and HTF metrics
            candles = await _binance_fetch_candles(symbol, "5m", 1000)
            if not candles or len(candles) < 2:
                return

            # UPSERT REST candles into existing buffer (same merge logic as WS handler)
            _candle_buffers.setdefault(symbol, {}).setdefault("5m", [])
            existing = _candle_buffers[symbol]["5m"]
            if existing:
                lookup = {c["timestamp"]: c for c in existing}
                for c in candles:
                    lookup[c["timestamp"]] = c
                merged = sorted(lookup.values(), key=lambda x: x["timestamp"])
            else:
                merged = candles[:]
            _candle_buffers[symbol]["5m"] = merged[-1000:]
            latest_ts = int(candles[-1]["timestamp"].replace(tzinfo=timezone.utc).timestamp() * 1000)
            if symbol not in last_processed_ts:
                last_processed_ts[symbol] = latest_ts
                return

            if latest_ts > last_processed_ts[symbol]:
                logger.info(f"[REST] {symbol} 5m: Candle closed @ {datetime.fromtimestamp(last_processed_ts[symbol]/1000, tz=timezone.utc)}")
                last_processed_ts[symbol] = latest_ts
                await _on_candle_close(symbol, "REST")

        while True:
            try:
                if not ohlcv_rest_fallback:
                    try:
                        ohlcvs = await asyncio.wait_for(
                            exchange.watch_ohlcv(symbol, "5m"),
                            timeout=120,
                        )
                        if not ohlcvs:
                            continue

                        # Convert WS candles to dicts
                        ws_candles = [
                            {
                                "timestamp": datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc).replace(tzinfo=None),
                                "open": c[1], "high": c[2], "low": c[3], "close": c[4],
                                "volume": c[5]
                            } for c in ohlcvs
                        ]
                        # UPSERT WS candles into existing buffer instead of replacing it.
                        # This prevents the buffer from shrinking if CCXT Pro returns
                        # an incomplete cache (e.g. after a WS reconnect).
                        # Uses timestamp-keyed dict so existing candles get UPDATED
                        # with final OHLCV data when a candle closes (critical for
                        # correct signal detection).
                        _candle_buffers.setdefault(symbol, {}).setdefault("5m", [])
                        existing = _candle_buffers[symbol]["5m"]
                        if existing:
                            # Build lookup: timestamp → candle
                            lookup = {c["timestamp"]: c for c in existing}
                            # Upsert: update existing + add new
                            for c in ws_candles:
                                lookup[c["timestamp"]] = c
                            # Convert back to sorted list
                            merged = sorted(lookup.values(), key=lambda x: x["timestamp"])
                        else:
                            merged = ws_candles[:]
                        _candle_buffers[symbol]["5m"] = merged[-1000:]

                        latest_ts = ohlcvs[-1][0]
                        if symbol not in last_processed_ts:
                            last_processed_ts[symbol] = latest_ts
                            continue

                        if latest_ts > last_processed_ts[symbol]:
                            logger.info(f"[WS] {symbol} 5m: Candle closed @ {datetime.fromtimestamp(last_processed_ts[symbol]/1000, tz=timezone.utc)}")
                            last_processed_ts[symbol] = latest_ts
                            await _on_candle_close(symbol, "WS")

                        ohlcv_ws_retries = 0
                    except asyncio.TimeoutError:
                        ohlcv_ws_retries += 1
                        if ohlcv_ws_retries >= 2:
                            ohlcv_rest_fallback = True
                    except Exception as e:
                        logger.warning(f"[WS] OHLCV error for {symbol}: {e}")
                        ohlcv_ws_retries += 1
                        if ohlcv_ws_retries >= 3:
                            ohlcv_rest_fallback = True
                        else:
                            await asyncio.sleep(10)
                else:
                    # REST fallback: poll every 60s for new candle closes
                    await _process_candle_close_rest()
                    _health["last_error_message"] = None  # Clear the visible error

                    # Try to reconnect WS every ~5 min
                    ohlcv_ws_retries += 1
                    if ohlcv_ws_retries >= 5:
                        logger.info(f"[WS] Attempting OHLCV WS reconnect for {symbol}...")
                        ohlcv_rest_fallback = False
                        ohlcv_ws_retries = 0
                        continue

                    await asyncio.sleep(60)

            except Exception as e:
                logger.warning(f"[WS] OHLCV error for {symbol}: {e}")
                _health["last_error_time"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                _health["last_error_message"] = f"OHLCV {symbol}: {e}"
                await asyncio.sleep(10)

    # Log buffer size periodically for diagnostics
    async def _buffer_diag_logger():
        """Log candle buffer stats every 5 minutes for debugging."""
        while True:
            await asyncio.sleep(300)
            for sym in SYMBOLS:
                buf = _candle_buffers.get(sym, {}).get("5m", [])
                if buf:
                    ts_from = buf[0]["timestamp"]
                    ts_to = buf[-1]["timestamp"]
                    logger.info(f"[Diag] {sym} 5m buffer: {len(buf)} candles, {ts_from} → {ts_to}")

    # Always-on REST ticker poller: fetches real Binance price every 30s
    # regardless of WebSocket state. This is the safety net that ensures
    # _latest_prices and _latest_ticks always reflect the current market price.
    async def _rest_ticker_poller():
        while True:
            for sym in SYMBOLS:
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.get(
                            f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={sym}"
                        )
                        if resp.status_code == 200:
                            t = resp.json()
                            price = float(t["lastPrice"])
                            _latest_prices[sym] = price
                            _latest_ticks[sym] = {
                                "symbol": sym,
                                "price": price,
                                "change_24h": round(float(t.get("priceChangePercent", 0) or 0), 2),
                                "high_24h": float(t.get("highPrice", price) or price),
                                "low_24h": float(t.get("lowPrice", price) or price),
                                "volume": round(float(t.get("volume", 0) or 0), 2),
                                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            }
                except Exception:
                    pass
            await asyncio.sleep(30)

    try:
        # Seed initial price immediately via REST before WebSocket connects
        logger.info("[Ticker] Seeding initial prices from Binance REST...")
        for sym in SYMBOLS:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={sym}")
                    if resp.status_code == 200:
                        t = resp.json()
                        price = float(t["lastPrice"])
                        _latest_prices[sym] = price
                        _latest_ticks[sym] = {
                            "symbol": sym,
                            "price": price,
                            "change_24h": round(float(t.get("priceChangePercent", 0) or 0), 2),
                            "high_24h": float(t.get("highPrice", price) or price),
                            "low_24h": float(t.get("lowPrice", price) or price),
                            "volume": round(float(t.get("volume", 0) or 0), 2),
                            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        }
                        logger.info(f"[Ticker] Initial price seeded for {sym}: ${price:.2f}")
            except Exception as e:
                logger.warning(f"[Ticker] Initial REST seed failed for {sym}: {e}")

        # Run ticker watcher, REST ticker poller, buffer diag, and OHLCV watchers in parallel
        ticker_task = asyncio.create_task(handle_tickers())
        rest_ticker_task = asyncio.create_task(_rest_ticker_poller())
        diag_task = asyncio.create_task(_buffer_diag_logger())
        ohlcv_tasks = [asyncio.create_task(handle_ohlcv(s)) for s in SYMBOLS]
        
        await asyncio.gather(ticker_task, rest_ticker_task, diag_task, *ohlcv_tasks)
    except asyncio.CancelledError:
        logger.info("[WS] Worker shutting down...")
    except Exception as e:
        logger.error(f"[WS] Critical worker error: {e}")
        _health["last_error_time"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _health["last_error_message"] = f"WS: {e}"
    finally:
        await exchange.close()



async def _htf_bias_worker():
    """
    Computes HTF bias from 1h candles.
    Primary: Binance WebSockets (via CCXT Pro) for real-time updates.
    Fallback: Binance REST API polling if WebSocket fails (e.g. DNS issues on stream.binance.com).
    """
    import ccxt.pro as ccxtpro

    rest_fallback = False
    ws_retries = 0
    max_ws_retries = 3
    _last_processed_1h_ts: int = 0

    async def _rest_check_bias():
        """Fetch 1h candles via REST and update bias if changed."""
        nonlocal _last_processed_1h_ts
        candles = await _binance_fetch_candles("ETHUSDT", "1H", 100)
        if not candles or len(candles) < 26:
            return False

        latest_ts = int(candles[-1]["timestamp"].replace(tzinfo=timezone.utc).timestamp() * 1000)
        if latest_ts <= _last_processed_1h_ts:
            return False

        _last_processed_1h_ts = latest_ts
        df_htf = pl.DataFrame(candles)
        new_bias = determine_bias_from_ema(df_htf, period=50)

        if new_bias == "neutral" and len(candles) >= 8:
            df_swings = _ict_ms.detect_swings(df_htf)
            new_bias = determine_bias_from_swings(df_swings)

        if new_bias != _health.get("htf_bias"):
            logger.info(f"[Bias] Shift: {new_bias.upper()} (REST)")
            _health["htf_bias"] = new_bias
            asyncio.ensure_future(_broadcast_data())
        return True

    # Seed initial bias immediately via REST (works even if WebSocket never connects)
    try:
        await _rest_check_bias()
        logger.info(f"[Bias] Initial bias (REST): {_health.get('htf_bias', 'neutral').upper()}")
    except Exception as e:
        logger.warning(f"[Bias] Initial REST fetch failed: {e}")

    while True:
        try:
            if not rest_fallback:
                # ── WebSocket path ────────────────────────────────────────
                exchange = ccxtpro.binanceusdm({
                    "enableRateLimit": True,
                })
                while not rest_fallback:
                    try:
                        ohlcvs = await exchange.watch_ohlcv("ETHUSDT", "1h")
                        if not ohlcvs or len(ohlcvs) < 26:
                            continue

                        df_htf = pl.DataFrame([
                            {"timestamp": c[0], "open": c[1], "high": c[2],
                             "low": c[3], "close": c[4], "volume": c[5]}
                            for c in ohlcvs
                        ])
                        new_bias = determine_bias_from_ema(df_htf, period=50)
                        if new_bias == "neutral" and len(ohlcvs) >= 8:
                            df_swings = _ict_ms.detect_swings(df_htf)
                            new_bias = determine_bias_from_swings(df_swings)

                        if new_bias != _health.get("htf_bias"):
                            logger.info(f"[Bias] Shift: {new_bias.upper()}")
                            _health["htf_bias"] = new_bias
                            asyncio.ensure_future(_broadcast_data())
                        ws_retries = 0
                    except asyncio.CancelledError:
                        await exchange.close()
                        raise
                    except Exception as e:
                        logger.warning(f"[Bias] WS error: {e}")
                        ws_retries += 1
                        if ws_retries >= max_ws_retries:
                            logger.warning(f"[Bias] Falling back to REST (WS failed {ws_retries}x)")
                            rest_fallback = True
                            break
                        await asyncio.sleep(5)

                await exchange.close()
            else:
                # ── REST fallback path ────────────────────────────────────
                # Update bias on new 1h candle close (poll every 60s)
                await _rest_check_bias()

                # Try to reconnect WebSocket every ~5 minutes
                ws_retries += 1
                if ws_retries >= 5:
                    logger.info("[Bias] Attempting WebSocket reconnect...")
                    rest_fallback = False
                    ws_retries = 0
                    continue

                await asyncio.sleep(60)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[Bias] Worker error: {e}")
            await asyncio.sleep(10)



async def _sync_worker():
    """Periodic exchange position reconciliation via orchestrator."""
    while True:
        try:
            await asyncio.sleep(30)
            if not _live_executor or not _live_executor.exchange:
                continue

            result = await _orchestrator.sync_exchange_positions(
                current_prices=dict(_latest_prices),
            )

            stats = _health.get("sync_stats", {})
            stats["total_cycles"] = stats.get("total_cycles", 0) + 1
            stats["total_closed_from_sl"] += result.get("positions_closed_sl", 0)
            stats["total_closed_from_tp"] += result.get("positions_closed_tp", 0)
            stats["total_closed_from_manual"] += result.get("positions_closed_manual", 0)
            stats["total_errors"] += len(result.get("errors", []))
            stats["last_sync_time"] = result.get("timestamp")
            stats["last_sync_result"] = {
                "demo_positions": result.get("demo_positions_checked", 0),
                "exchange_positions": result.get("exchange_positions_checked", 0),
                "closed_sl": result.get("positions_closed_sl", 0),
                "closed_tp": result.get("positions_closed_tp", 0),
                "closed_manual": result.get("positions_closed_manual", 0),
                "discrepancies": len(result.get("discrepancies", [])),
                "errors": len(result.get("errors", [])),
            }

            total_closed = (result.get("positions_closed_sl", 0) +
                           result.get("positions_closed_tp", 0) +
                           result.get("positions_closed_manual", 0))
            if total_closed > 0:
                logger.info(f"[Sync] Cycle: {result.get('demo_positions_checked')} demo, "
                           f"{result.get('exchange_positions_checked')} exchange, "
                           f"{total_closed} closed")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[Sync] Worker error: {e}")


# ── Endpoints ────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "status": "online",
        "version": "0.1.0",
        "data_source": "Binance REST",
    }


def format_signal(s: Dict) -> Dict:
    details = s.get("details", {})
    return {
        "id": s.get("id", 0),
        "symbol": s.get("symbol", "ETHUSDT"),
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


@app.get("/signals")
async def get_signals(limit: int = Query(10, ge=1, le=100)):
    if not _recent_signals:
        return []
    return [format_signal(s) for s in _recent_signals[:limit]]


@app.get("/signals/{signal_id}")
async def get_signal_detail(signal_id: int):
    for s in _recent_signals:
        if s.get("id") == signal_id:
            return format_signal(s)
    raise HTTPException(status_code=404, detail="Signal not found")


@app.get("/candles/{symbol}")
async def get_candles(symbol: str, timeframe: str = "1h", limit: int = 100):
    symbol = symbol.upper()
    if symbol != "ETHUSDT":
        return {"error": f"Unsupported symbol: {symbol}. Only ETHUSDT is available.", "data": []}

    try:
        # 1. Check if we have this data in our real-time buffers
        if symbol in _candle_buffers and timeframe in _candle_buffers[symbol]:
            candles = _candle_buffers[symbol][timeframe][-limit:]
        else:
            # 2. Fallback to fresh Binance fetch for untracked timeframes (like 1h)
            tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}
            bar = tf_map.get(timeframe, "1H")
            candles = await _binance_fetch_candles(symbol, bar, limit)

        if not candles:
            return []

        return [
            {
                "id": i + 1, "symbol": symbol,
                "timeframe": timeframe,
                "timestamp": c["timestamp"].isoformat() + "Z"
                if hasattr(c["timestamp"], "isoformat") else str(c["timestamp"]),
                "open": c["open"], "high": c["high"],
                "low": c["low"], "close": c["close"], "volume": c["volume"],
            }
            for i, c in enumerate(candles)
        ]
    except Exception as e:
        logger.error(f"Candle fetch failed for {symbol}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch candles: {e}")


@app.get("/backtest-data/{symbol}")
async def get_backtest_data(
    symbol: str,
    days: int = Query(30, ge=1, le=90),
    bar: str = Query("5m", pattern="^(1m|5m|15m|1H|4H|1D)$"),
    before: Optional[str] = Query(None, description="ISO timestamp to end the window (default: now)"),
):
    """Fetch paginated historical data from Binance for backtesting."""
    symbol = symbol.upper()
    if symbol != "ETHUSDT":
        raise HTTPException(status_code=400, detail=f"Unsupported symbol: {symbol}. Only ETHUSDT is available.")

    try:
        per_day = {"1m": 720, "5m": 288, "15m": 96, "1H": 24, "4H": 6, "1D": 1}.get(bar, 288)
        total_needed = days * per_day
        interval = BINANCE_BAR_MAP.get(bar)
        if not interval:
            raise HTTPException(status_code=400, detail=f"Unsupported bar: {bar}")

        all_candles: List[Dict] = []
        page_end: Optional[datetime] = None
        if before:
            # Replace trailing Z with +00:00 for fromisoformat compatibility
            before_clean = before.replace("Z", "+00:00")
            page_end = datetime.fromisoformat(before_clean)

        while len(all_candles) < total_needed:
            url = "https://fapi.binance.com/fapi/v1/klines"
            params = {"symbol": symbol, "interval": interval, "limit": "1000"}
            if page_end:
                params["endTime"] = str(int(page_end.timestamp() * 1000))

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    break
                klines = resp.json()
                if not isinstance(klines, list) or len(klines) == 0:
                    break

                batch = []
                for k in klines:
                    batch.append({
                        "timestamp": datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc).replace(tzinfo=None),
                        "open": float(k[1]), "high": float(k[2]),
                        "low": float(k[3]), "close": float(k[4]),
                        "volume": float(k[5]),
                    })
                all_candles.extend(batch)
                page_end = batch[0]["timestamp"]  # type: ignore[assignment]
                await asyncio.sleep(0.1)

        if not all_candles:
            return []

        seen = set()
        deduped = []
        for c in all_candles:
            key = c["timestamp"].timestamp()
            if key not in seen:
                seen.add(key)
                deduped.append(c)

        deduped.sort(key=lambda c: c["timestamp"])
        deduped = deduped[:total_needed]
        logger.info(f"[Backtest] Fetched {len(deduped)} {bar} candles for {symbol} ({days}d)")

        return [
            {
                "id": i + 1, "symbol": symbol, "timeframe": bar,
                "timestamp": c["timestamp"].isoformat() + "Z"
                if hasattr(c["timestamp"], "isoformat") else str(c["timestamp"]),
                "open": c["open"], "high": c["high"],
                "low": c["low"], "close": c["close"], "volume": c["volume"],
            }
            for i, c in enumerate(deduped)
        ]

    except Exception as e:
        logger.error(f"[Backtest] Fetch failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch backtest data: {e}")


@app.get("/trades")
async def get_trades(
    limit: int = Query(20, ge=1, le=200),
    result: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
):
    # Always read fresh from DemoAccount — never stale
    trades = _demo_account.get_closed_trades_list(limit=limit)
    if result:
        trades = [t for t in trades if t.get("result") == result]
    if symbol:
        trades = [t for t in trades if t.get("symbol", "").upper() == symbol.upper()]

    result_trades = []
    for i, t in enumerate(trades[:limit]):
        result_trades.append({
            "id": i + 1, "symbol": t.get("symbol", "ETHUSDT"),
            "signal_type": t.get("signal_type", "NEUTRAL"),
            "entry_time": (
                t["entry_time"].isoformat()
                if hasattr(t.get("entry_time"), "isoformat") else str(t.get("entry_time", ""))
            ),
            "exit_time": (
                t["exit_time"].isoformat()
                if hasattr(t.get("exit_time"), "isoformat") else str(t.get("exit_time", ""))
            ),
            "entry_price": t.get("entry_price", 0),
            "exit_price": t.get("exit_price", 0),
            "profit": t.get("profit", 0),
            "rr": t.get("rr", 0),
            "result": t.get("result", "BREAK_EVEN"),
            "exit_reason": t.get("exit_reason", ""),
        })
    return result_trades


@app.get("/performance")
async def get_performance():
    # Always read fresh from DemoAccount — never stale
    p = _demo_account.get_performance()
    if not p or p.get("total_trades", 0) == 0:
        return {"win_rate": 0.0, "total_pnl": 0.0, "profit_factor": 0.0,
                "max_drawdown": 0.0, "sharpe_ratio": 0.0, "total_trades": 0, "avg_rr": 0.0}
    return {
        "win_rate": p.get("win_rate", 0.0),
        "total_pnl": p.get("total_profit", 0.0),
        "profit_factor": p.get("profit_factor", 0.0),
        "max_drawdown": p.get("max_drawdown", 0.0),
        "sharpe_ratio": p.get("sharpe_ratio", 0.0),
        "total_trades": p.get("total_trades", 0),
        "avg_rr": p.get("avg_rr", 0.0),
    }


@app.get("/demo/account")
async def get_demo_account():
    # Always read fresh from DemoAccount — never stale
    perf = _demo_account.get_performance()
    open_positions = DemoAccount.enrich_positions(
        _demo_account.get_open_positions_list(), dict(_latest_prices),
    )
    initial_balance = _demo_account.initial_balance
    return {
        "balance": perf.get("capital_remaining", initial_balance),
        "initial_balance": initial_balance,
        "total_profit": perf.get("total_profit", 0.0),
        "total_trades": perf.get("total_trades", 0),
        "win_rate": perf.get("win_rate", 0.0),
        "profit_factor": perf.get("profit_factor", 0.0),
        "max_drawdown": perf.get("max_drawdown", 0.0),
        "avg_rr": perf.get("avg_rr", 0.0),
        "total_wins": perf.get("total_wins", 0),
        "total_losses": perf.get("total_losses", 0),
        "peak_balance": perf.get("peak_balance", initial_balance),
        "current_drawdown_pct": perf.get("current_drawdown_pct", 0.0),
        "open_positions_count": len(open_positions),
        "open_positions": open_positions,
    }


@app.get("/api/diagnostics")
async def get_diagnostics():
    """Detailed system diagnostics for the dashboard."""
    return {
        "websocket": {
            "status": _health.get("status"),
            "data_source": _health.get("data_sources", [])[0],
            "last_cycle": _health.get("last_cycle_time"),
            "cycle_count": _health.get("cycle_count"),
        },
        "bias": {
            "htf_bias": _health.get("htf_bias"),
            "eth_price": _latest_prices.get("ETHUSDT"),
        },
        "database": {
            "connected": True, # Managed by SQLAlchemy aiosqlite
            "total_trades": len(_demo_account.closed_trades),
        },
        "risk": {
            "daily_loss_pct": round(_demo_account.daily_loss / _demo_account.initial_balance * 100, 2),
            "open_positions": len(_demo_account.open_positions),
        }
    }


@app.get("/api/health")
async def get_health():
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    uptime = now
    if _health.get("started_at"):
        started = datetime.fromisoformat(_health["started_at"].replace("Z", "+00:00"))
        uptime_secs = (datetime.now(timezone.utc) - started).total_seconds()
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
        "eth_price": _latest_prices.get("ETHUSDT", 0),
    }


@app.post("/reset")
async def reset_all():
    await _orchestrator.reset_all(initial_balance=DEMO_INITIAL_BALANCE)

    global _recent_signals
    _recent_signals = []

    _health["total_signals_generated"] = 0
    _health["total_signals_kept"] = 0
    _health["total_trades_executed"] = 0
    _health["last_cycle_time"] = None
    _health["sync_stats"] = {
        "total_cycles": 0, "total_closed_from_sl": 0, "total_closed_from_tp": 0,
        "total_closed_from_manual": 0, "total_errors": 0,
        "last_sync_time": None, "last_sync_result": None,
    }

    logger.info("[Reset] All state cleared — fresh start.")
    return {
        "status": "ok",
        "message": f"All state cleared. DemoAccount reset to ${DEMO_INITIAL_BALANCE:.2f} with 0 trades.",
        "demo_balance": DEMO_INITIAL_BALANCE,
        "demo_open_positions": 0,
        "demo_closed_trades": 0,
    }


@app.post("/sync")
async def trigger_sync():
    if not _live_executor or not _live_executor.exchange:
        raise HTTPException(status_code=503, detail="No exchange connection available")

    try:
        result = await _orchestrator.sync_exchange_positions(
            current_prices=dict(_latest_prices),
        )
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")


@app.get("/risk/status")
async def get_risk_status():
    return {
        "max_risk_per_trade_pct": MAX_RISK_PER_TRADE_PCT,
        "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
        "max_weekly_loss_pct": 6.0,
        "max_open_positions": MAX_OPEN_POSITIONS,
        "current_daily_loss_pct": round(
            _demo_account.daily_loss
            / (DEMO_INITIAL_BALANCE * MAX_DAILY_LOSS_PCT / 100)
            * MAX_DAILY_LOSS_PCT
            if MAX_DAILY_LOSS_PCT > 0 else 0, 2
        ),
        "current_weekly_loss_pct": 0.0,
        "open_positions_count": len(_demo_account.open_positions),
        "account_balance": _demo_account.balance,
    }


# ── WebSocket Price Stream ───────────────────────────────────────────

def _build_price_tick(symbol: str = "ETHUSDT") -> dict:
    """Build a price tick dict, preferring _latest_ticks and falling back to _latest_prices."""
    if symbol in _latest_ticks and _latest_ticks[symbol]:
        return _latest_ticks[symbol]
    price = _latest_prices.get(symbol, 1800.0)
    return {
        "symbol": symbol, "price": price, "change_24h": 0.0,
        "high_24h": price, "low_24h": price, "volume": 0.0,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@app.websocket("/ws/prices")
async def ws_price_stream(websocket: WebSocket):
    await websocket.accept()

    # Send initial tick immediately — always has data thanks to seeded defaults
    for symbol in SYMBOLS:
        await websocket.send_json(_build_price_tick(symbol))

    try:
        while True:
            for symbol in SYMBOLS:
                await websocket.send_json(_build_price_tick(symbol))
                await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@app.websocket("/ws/data")
async def ws_data_stream(websocket: WebSocket):
    """
    Real-time data stream for signals, trades, demo account, risk, performance, and health.
    On connect: sends a full snapshot immediately.
    Then: pushes a new snapshot whenever the crypto/bias workers update state.
    Also sends a heartbeat every 30s to keep the connection alive.
    """
    await websocket.accept()
    _ws_clients.add(websocket)

    try:
        # Send initial snapshot immediately
        payload = _build_ws_payload()
        await websocket.send_json(payload)

        # Heartbeat loop — keeps connection alive, sends periodic refreshes
        while True:
            await asyncio.sleep(30)
            try:
                payload = _build_ws_payload()
                await websocket.send_json(payload)
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _ws_clients.discard(websocket)


# ── Dashboard static files ───────────────────────────────────────────

from fastapi.staticfiles import StaticFiles
import os as _os

_dashboard_dir = _os.path.join(_os.path.dirname(__file__), "static")
if _os.path.isdir(_dashboard_dir) and _os.path.exists(_os.path.join(_dashboard_dir, "index.html")):
    app.mount("/dashboard", StaticFiles(directory=_dashboard_dir, html=True), name="dashboard")
    logger.info(f"Dashboard available at /dashboard — {_dashboard_dir}")
else:
    logger.info("No dashboard build found — API-only mode (run 'cd dashboard && npm run build' to enable)")

