"""
12-Month Rolling Backtest — One Month at a Time

Fetches 30 days of 5m data per month via Binance klines API (direct, no
intermediary server), drives DemoAccount candle-by-candle matching live
system logic exactly.

Runs months sequentially (oldest first → most recent) to avoid timeouts.
Each month: 2 symbols (BTC, ETH), ~8640 candles each, full ICT pipeline.

Usage:
    python backtest_okx.py              # last 12 months
    python backtest_okx.py --months 6   # last 6 months
"""

import asyncio
import httpx
import polars as pl
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from loguru import logger
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from ict_engine.market_structure import MarketStructure
from ict_engine.fvg import FVGDetector
from ict_engine.order_blocks import OrderBlockDetector
from ict_engine.liquidity import LiquidityDetector
from ict_engine.sessions import SessionDetector
from ict_engine.premium_discount import PremiumDiscountDetector
from signal_engine.engine import SignalEngine, determine_bias_from_swings, determine_bias_from_ema
from demo_account import DemoAccount, ClosedTrade
import json

# ── Data source mapping ────────────────────────────────────────────
BINANCE_BAR_MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
# Default capital; override with --capital <amount> (e.g. --capital 10000)
BACKTEST_CAPITAL = 5_000.0
MAX_OPEN_POSITIONS = 3

_ict_ms = MarketStructure(n=3)
_ict_fvg = FVGDetector()
_ict_ob = OrderBlockDetector()
_ict_liquidity = LiquidityDetector(atr_threshold=0.10)
_ict_sessions = SessionDetector()
_ict_pd = PremiumDiscountDetector()
_signal_engine = SignalEngine()


async def fetch_historical_data(symbol: str, bar: str, days: int,
                                 before: Optional[str] = None) -> pl.DataFrame:
    """Fetch paginated historical data from Binance REST API.

    Uses Binance klines endpoint (1000 per page). Public endpoint —
    no API key needed. Paginates, deduplicates, returns sorted Polars DataFrame.

    Args:
        symbol: BTCUSDT or ETHUSDT
        bar: 5m, 1H, etc.
        days: Number of days of data to fetch (1-90)
        before: ISO date string to end the window (e.g. "2025-06-15").
                Defaults to now.
    """
    interval = BINANCE_BAR_MAP.get(bar)
    if not interval:
        return pl.DataFrame()

    per_day = {"1m": 720, "5m": 288, "15m": 96, "1H": 24, "4H": 6, "1D": 1}.get(bar, 288)
    total_needed = days * per_day

    end_ts = None
    if before:
        before_clean = before.replace("Z", "+00:00") if isinstance(before, str) else before
        end_ts = datetime.fromisoformat(before_clean)

    all_candles: List[Dict] = []
    page_end = end_ts
    url = "https://api.binance.com/api/v3/klines"

    while len(all_candles) < total_needed:
        params = {"symbol": symbol, "interval": interval, "limit": "1000"}
        if page_end:
            params["endTime"] = str(int(page_end.timestamp() * 1000))

        try:
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
                        "timestamp": datetime.fromtimestamp(int(k[0]) / 1000),
                        "open": float(k[1]), "high": float(k[2]),
                        "low": float(k[3]), "close": float(k[4]),
                        "volume": float(k[5]),
                    })
                all_candles.extend(batch)
                page_end = batch[0]["timestamp"]  # oldest in this batch
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.warning(f"[Binance] History fetch failed for {symbol} {bar}: {e}")
            break

    if not all_candles:
        logger.warning(f"[Binance] No data fetched for {symbol} {bar} ({days}d)")
        return pl.DataFrame()

    seen = set()
    deduped = []
    for c in all_candles:
        key = c["timestamp"].timestamp()
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    deduped.sort(key=lambda c: c["timestamp"])
    deduped = deduped[:total_needed]
    df = pl.DataFrame(deduped).sort("timestamp")
    label = f" before {before}" if before else ""
    logger.info(f"  [Binance] Fetched {len(df)} {bar} candles for {symbol} ({days}d{label})")
    return df


def precompute_ict(df: pl.DataFrame) -> pl.DataFrame:
    """Run the full 7-module ICT pipeline once on a DataFrame.

    This is the critical optimization: instead of re-running the entire
    ICT pipeline on every candle (as the old run_ict_on_buffer did),
    we compute everything once in a single vectorized pass.
    """
    df = df.clone()
    df = _ict_ms.detect_swings(df)
    df = _ict_ms.detect_bos_mss(df)
    df = _ict_fvg.detect_fvgs(df)
    df = _ict_ob.detect_order_blocks(df)
    df = _ict_liquidity.detect_all(df)
    df = _ict_sessions.detect_sessions(df)
    df = _ict_pd.compute_zones(df)
    return df


def extract_signal_at_candle(df_ict: pl.DataFrame, candle_idx: int,
                             htf_bias: str, current_price: float,
                             min_score: int = 80) -> Optional[Dict]:
    """
    Extract signal from pre-computed ICT columns at a given candle index.

    Uses a tiny 5-row tail slice of the pre-computed DataFrame (instead of
    re-running the full ICT pipeline on a 288-candle buffer every time).

    The signal engine's `generate_signal` only looks at:
      - `df.tail(1)` for current price, timestamp, zone, OTE
      - `df["fvg_type"].tail(5).any()` for recent FVG presence
      - `df["ob_type"].tail(5).any()` for recent OB presence
    So a 5-row slice is all we need.
    """
    if candle_idx < 5:
        return None

    # Tiny slice: just the last 5 closed candles (up to candle_idx - 1)
    buf = df_ict.slice(candle_idx - 5, min(5, candle_idx))
    if len(buf) < 2:
        return None

    mss_type = None
    if "mss" in buf.columns:
        latest_mss = buf["mss"].drop_nulls().tail(1)
        if len(latest_mss) > 0:
            mss_type = latest_mss[0]

    sweep_type = None
    if "liquidity_sweep_type" in buf.columns:
        latest_sweep = buf["liquidity_sweep_type"].drop_nulls().tail(1)
        if len(latest_sweep) > 0:
            sweep_type = latest_sweep[0]

    latest_row = buf.tail(1).to_dicts()[0]
    atr = latest_row.get("atr", 0) or 0.0

    signal = _signal_engine.generate_signal(
        buf, mss_type=mss_type, sweep_type=sweep_type,
        timeframe="5m", htf_bias=htf_bias,
    )
    signal["symbol"] = ""
    signal["id"] = None
    signal["atr"] = atr

    score = signal.get("score", 0)
    signal_type = signal.get("signal_type", "NEUTRAL")
    in_kz = signal.get("in_kill_zone", False)

    if score < min_score or not in_kz or signal_type == "NEUTRAL":
        return None
    if htf_bias != "neutral" and not signal.get("htf_aligned", True):
        return None

    signal["price"] = current_price
    return signal


def check_position_vs_candle(pos, candle_high: float, candle_low: float, current_ts):
    """Check if candle H/L breaches SL/TP. Returns (exit_reason, exit_price) or (None, None)."""
    if pos.side == "LONG":
        if candle_high >= pos.take_profit:
            return "TAKE_PROFIT", pos.take_profit
        elif candle_low <= pos.stop_loss:
            return "STOP_LOSS", pos.stop_loss
    else:
        if candle_low <= pos.take_profit:
            return "TAKE_PROFIT", pos.take_profit
        elif candle_high >= pos.stop_loss:
            return "STOP_LOSS", pos.stop_loss
    return None, None


def close_position(demo, pos, exit_price, exit_reason, current_ts):
    """Close a position and update DemoAccount state."""
    if pos.side == "LONG":
        profit = (exit_price - pos.entry_price) * pos.quantity
    else:
        profit = (pos.entry_price - exit_price) * pos.quantity

    rr = abs(exit_price - pos.entry_price) / abs(pos.entry_price - pos.stop_loss) \
        if abs(pos.entry_price - pos.stop_loss) > 0 else 0
    result = "WIN" if profit > 0 else ("LOSS" if profit < 0 else "BREAK_EVEN")

    demo.balance += profit
    demo._daily_pnl += profit
    if demo.balance > demo._peak_balance:
        demo._peak_balance = demo.balance

    # Record stop loss for cooldown tracking (matches live _check_position behavior)
    if exit_reason == "STOP_LOSS":
        demo._last_sl[pos.symbol] = {"time": current_ts, "side": pos.side}

    trade = ClosedTrade(
        symbol=pos.symbol, signal_type=pos.signal_type, side=pos.side,
        entry_time=pos.entry_time, exit_time=current_ts,
        entry_price=pos.entry_price, exit_price=exit_price,
        stop_loss=pos.stop_loss, take_profit=pos.take_profit,
        quantity=pos.quantity, profit=profit,
        profit_pct=(exit_price - pos.entry_price) / pos.entry_price if pos.side == "LONG"
                    else (pos.entry_price - exit_price) / pos.entry_price,
        rr=round(rr, 2), result=result, exit_reason=exit_reason,
    )
    demo.closed_trades.append(trade)
    del demo.open_positions[pos.symbol]


async def backtest_symbol(symbol: str, chunk_size: int = 500,
                          before: Optional[str] = None,
                          debug: bool = False,
                          spot: bool = False) -> Dict:
    """Run 30-day backtest using DemoAccount.

    Args:
        symbol: BTCUSDT or ETHUSDT
        chunk_size: Candles per processing chunk
        before: ISO date to end the 30-day window (default: now)
        debug: Enable per-trade debug logging and analysis
        spot: If True, only trade LONG (skip SHORT signals — matches live spot executor)
    """
    days = 30  # fixed 30-day window per month

    # 1. Fetch 5m data for this window
    t0 = datetime.now(timezone.utc)
    df_5m_full = await fetch_historical_data(symbol, "5m", days, before=before)
    if df_5m_full.is_empty() or len(df_5m_full) < 100:
        return {"symbol": symbol, "month": str(before or "latest"),
                "total_trades": 0, "total_profit": 0,
                "result": f"Only {len(df_5m_full)} candles"}

    data_range = f"{df_5m_full['timestamp'].min().strftime('%b %d')} → " \
                 f"{df_5m_full['timestamp'].max().strftime('%b %d')}"
    logger.info(f"  Range: {data_range}, {len(df_5m_full)} candles "
                f"[fetch: {(datetime.now(timezone.utc)-t0).total_seconds():.0f}s]")

    # 2. Fetch 1h data for HTF bias
    df_1h = await fetch_historical_data(symbol, "1H", days, before=before)
    htf_bias = "neutral"
    if not df_1h.is_empty() and len(df_1h) >= 26:
        df_1h_init = df_1h.slice(0, min(168, len(df_1h)))
        htf_bias = determine_bias_from_ema(df_1h_init, fast=12, slow=26, threshold_pct=0.5)
        swing_bias = determine_bias_from_swings(_ict_ms.detect_swings(df_1h_init))
        logger.info(f"  Initial HTF bias: {htf_bias.upper()} (EMA) swings: {swing_bias.upper()}")
    else:
        logger.info(f"  Initial HTF bias: neutral ({len(df_1h)} 1h candles)")

    rows = df_5m_full.to_dicts()
    total_candles = len(rows)

    # Both symbols now use identical settings: 0.5× SL, no cooldown, min_score=60
    symbol_min_score = 60

    demo = DemoAccount(
        initial_balance=BACKTEST_CAPITAL, risk_per_trade_pct=1.0,
        max_daily_loss_pct=3.0, max_open_positions=MAX_OPEN_POSITIONS,
        sl_multiplier=0.5,
        reentry_cooldown_minutes=0,
        symbol_min_scores={symbol.upper(): symbol_min_score},
        spot_only=spot,
    )

    signals_gen = 0
    signals_kept = 0
    bias_changes = 0

    # Debug tracking
    trade_log: List[Dict] = []
    current_trade_start: Dict[str, Dict] = {}

    # Pre-compute all ICT columns once on the full 5m dataset
    # This replaces the per-candle run_ict_on_buffer calls (~8,640 calls → 1 call)
    logger.info(f"    Pre-computing ICT columns...")
    t_ict = datetime.now(timezone.utc)
    df_ict = precompute_ict(df_5m_full)
    ict_elapsed = (datetime.now(timezone.utc) - t_ict).total_seconds()
    logger.info(f"    ICT pre-compute: {ict_elapsed:.1f}s for {len(df_ict)} rows")

    # 5. Process in chunks with periodic HTF bias recomputation
    HTF_REFRESH_INTERVAL = 288  # ~1 day in 5m candles
    warmup = 50  # need enough data for rolling indicators
    i = warmup
    last_bias_refresh = 0

    while i < total_candles:
        chunk_end = min(i + chunk_size, total_candles)
        chunk_rows = rows[i:chunk_end]

        # Recompute HTF bias periodically
        if i - last_bias_refresh >= HTF_REFRESH_INTERVAL:
            current_ts = rows[i]["timestamp"]
            df_1h_slice = df_1h.filter(pl.col("timestamp") <= current_ts)
            df_1h_window = df_1h_slice.tail(min(168, len(df_1h_slice)))
            if len(df_1h_window) >= 26:
                new_bias = determine_bias_from_ema(df_1h_window, fast=12, slow=26, threshold_pct=0.5)
                if new_bias != htf_bias:
                    logger.info(f"    [Bias] {htf_bias.upper()} → {new_bias.upper()} @ candle {i}")
                    htf_bias = new_bias
                    bias_changes += 1
            last_bias_refresh = i

        for j, current in enumerate(chunk_rows):
            current_price = current["close"]
            current_ts = current["timestamp"]
            candle_idx = i + j

            # Step 1: Check open positions against candle H/L (every 5m candle)
            for sym in list(demo.open_positions.keys()):
                if sym != symbol:
                    continue
                pos = demo.open_positions[sym]
                reason, price = check_position_vs_candle(pos, current["high"], current["low"], current_ts)
                if reason is not None:
                    # Debug: log trade before closing
                    if debug and sym in current_trade_start:
                        held = candle_idx - current_trade_start[sym].get("candle_idx", candle_idx)
                        trade_log.append({
                            "symbol": pos.symbol, "side": pos.side,
                            "signal_type": pos.signal_type,
                            "atr": round(pos.atr, 4),
                            "entry_price": round(pos.entry_price, 2),
                            "exit_price": round(price, 2),
                            "stop_loss": round(pos.stop_loss, 2),
                            "take_profit": round(pos.take_profit, 2),
                            "sl_distance": round(abs(pos.entry_price - pos.stop_loss), 2),
                            "tp_distance": round(abs(pos.take_profit - pos.entry_price), 2),
                            "profit": round(((price - pos.entry_price) * pos.quantity
                                              if pos.side == "LONG"
                                              else (pos.entry_price - price) * pos.quantity), 2),
                            "result": "WIN" if ((price - pos.entry_price) * pos.quantity
                                                  if pos.side == "LONG"
                                                  else (pos.entry_price - price) * pos.quantity) > 0 else "LOSS",
                            "exit_reason": reason,
                            "held_candles": held,
                            "entry_ts": pos.entry_time.isoformat(),
                            "exit_ts": current_ts.isoformat(),
                        })
                    close_position(demo, pos, price, reason, current_ts)
                    if debug and sym in current_trade_start:
                        del current_trade_start[sym]

            # Step 2: Extract signal from pre-computed ICT columns (fast: no pipeline re-run)
            aligned = []
            sig = extract_signal_at_candle(df_ict, candle_idx, htf_bias, current_price,
                                             min_score=symbol_min_score)
            if sig is not None:
                sig["symbol"] = symbol
                sig["timestamp"] = current_ts
                signals_gen += 1

                # HTF alignment filter
                if htf_bias != "neutral":
                    if sig.get("htf_aligned", True):
                        aligned = [sig]
                        signals_kept += 1
                else:
                    aligned = []

            # Step 3: Spot mode filter — skip SHORT signals (not executable on spot)
            if spot and aligned and aligned[0].get("signal_type", "").startswith("SELL"):
                aligned = []

            # Step 4: Feed signals to DemoAccount
            prev_positions = set(demo.open_positions.keys())
            demo.process_signals(aligned, {symbol: current_price}, current_time=current_ts)
            # Debug: track when new positions open
            if debug:
                for sym in demo.open_positions.keys():
                    if sym not in prev_positions:
                        current_trade_start[sym] = {"candle_idx": candle_idx, "entry_ts": current_ts}

        i = chunk_end

        # Progress report
        pct = (i / total_candles) * 100
        elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
        cps = i / elapsed if elapsed > 0 else 0
        logger.info(f"    [{symbol}] {pct:.0f}% — {i}/{total_candles} "
                    f"({cps:.0f} c/s, {elapsed:.0f}s)")

    # Collect results
    perf = demo.get_performance()
    trades = demo.get_closed_trades_list(500)
    open_pos = demo.get_open_positions_list()

    wins = sum(1 for t in trades if t["result"] == "WIN")
    losses = sum(1 for t in trades if t["result"] == "LOSS")
    breakeven = sum(1 for t in trades if t["result"] == "BREAK_EVEN")

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    logger.info(f"  ── {symbol} Results ──")
    logger.info(f"  Trades: {perf['total_trades']} (W:{wins} L:{losses} BE:{breakeven}) | "
                f"WR: {perf['win_rate']*100:.1f}% | PF: {perf['profit_factor']:.2f}")
    logger.info(f"  P&L: ${perf['total_profit']:.2f} | DD: {perf['max_drawdown']*100:.1f}% | "
                f"Avg RR: {perf['avg_rr']:.2f} | Open: {len(open_pos)}")

    # Build date range string from actual candle timestamps
    ts_min = df_5m_full['timestamp'].min().strftime('%b %d')
    ts_max = df_5m_full['timestamp'].max().strftime('%b %d')
    data_range_str = f"{ts_min} → {ts_max}"

    result = {
        "symbol": symbol, "month": str(before or "latest"),
        "data_range": data_range_str,
        "htf_bias": htf_bias, "total_trades": perf["total_trades"],
        "wins": wins, "losses": losses, "breakeven": breakeven,
        "win_rate": perf["win_rate"], "total_profit": perf["total_profit"],
        "profit_factor": perf["profit_factor"], "max_drawdown": perf["max_drawdown"],
        "avg_rr": perf["avg_rr"], "capital_remaining": perf["capital_remaining"],
        "signals_gen": signals_gen, "signals_kept": signals_kept,
        "still_open": len(open_pos), "bias_changes": bias_changes,
    }
    if debug:
        result["trade_log"] = trade_log
    return result


def print_month_result(month_num: int, month_label: str, data_range: str,
                       r1: Dict, r2: Optional[Dict] = None):
    """Print a formatted monthly result block."""
    print(f"\n  {'─'*60}")
    print(f"  Month {month_num}/12 — {month_label}")
    print(f"  {data_range}")
    print(f"  {'─'*60}")

    results_to_print = [r for r in [r1, r2] if r is not None]
    for r in results_to_print:
        if r.get("total_trades", 0) == 0:
            print(f"  {r['symbol']}: {r.get('result', 'No trades')} ({r.get('htf_bias', '?').upper()})")
            continue

        print(f"  {r['symbol']}  ({r['htf_bias'].upper()})  "
              f"Trades: {r['total_trades']}  "
              f"W:{r['wins']} L:{r['losses']} BE:{r['breakeven']}  "
              f"Open: {r['still_open']}")
        print(f"    WR: {r['win_rate']*100:.1f}%  "
              f"PF: {r['profit_factor']:.2f}  "
              f"P&L: ${r['total_profit']:.2f}  "
              f"DD: {r['max_drawdown']*100:.1f}%  "
              f"RR: {r['avg_rr']:.2f}")


def print_combined_summary(all_results: List[Dict], num_months: int):
    """Print aggregated multi-month summary."""
    print(f"\n\n{'='*70}")
    print(f"  {num_months}-MONTH COMBINED SUMMARY")
    print(f"{'='*70}")

    all_btc = [r for r in all_results if r["symbol"] == "BTCUSDT"]
    all_eth = [r for r in all_results if r["symbol"] == "ETHUSDT"]

    grand_total = {"btc": {"trades": 0, "wins": 0, "losses": 0, "profit": 0.0,
                           "dd_sum": 0.0, "dd_count": 0, "rr_sum": 0.0, "rr_count": 0,
                           "signals_gen": 0, "signals_kept": 0},
                   "eth": {"trades": 0, "wins": 0, "losses": 0, "profit": 0.0,
                           "dd_sum": 0.0, "dd_count": 0, "rr_sum": 0.0, "rr_count": 0,
                           "signals_gen": 0, "signals_kept": 0}}

    for r in all_results:
        sym = "btc" if r["symbol"] == "BTCUSDT" else "eth"
        g = grand_total[sym]
        trades = r.get("total_trades", 0)
        g["trades"] += trades
        g["wins"] += r.get("wins", 0)
        g["losses"] += r.get("losses", 0)
        g["profit"] += r.get("total_profit", 0.0)
        g["signals_gen"] += r.get("signals_gen", 0)
        g["signals_kept"] += r.get("signals_kept", 0)
        if trades > 0:
            g["dd_sum"] += r.get("max_drawdown", 0.0)
            g["dd_count"] += 1
            g["rr_sum"] += r.get("avg_rr", 0.0) * trades
            g["rr_count"] += trades

    for label, g in [("BTCUSDT", grand_total["btc"]), ("ETHUSDT", grand_total["eth"])]:
        if g["trades"] == 0:
            print(f"\n  {label}: No trades across all months")
            continue
        wr = g["wins"] / g["trades"] * 100 if g["trades"] > 0 else 0
        avg_dd = g["dd_sum"] / g["dd_count"] * 100 if g["dd_count"] > 0 else 0
        avg_rr = g["rr_sum"] / g["rr_count"] if g["rr_count"] > 0 else 0
        print(f"\n  {label}")
        print(f"    Total trades: {g['trades']}  (W:{g['wins']} L:{g['losses']})")
        print(f"    Win rate:     {wr:.1f}%")
        print(f"    Total P&L:    ${g['profit']:.2f}")
        print(f"    Avg DD:       {avg_dd:.1f}%")
        print(f"    Avg RR:       {avg_rr:.2f}")
        print(f"    Signals:      {g['signals_gen']} gen → {g['signals_kept']} kept")

    combined_trades = grand_total["btc"]["trades"] + grand_total["eth"]["trades"]
    combined_profit = grand_total["btc"]["profit"] + grand_total["eth"]["profit"]
    combined_wins = grand_total["btc"]["wins"] + grand_total["eth"]["wins"]

    print(f"\n  {'─'*55}")
    print(f"  COMBINED (Both Symbols)")
    print(f"  {'─'*55}")
    print(f"  Total trades: {combined_trades}")
    if combined_trades > 0:
        wr = combined_wins / combined_trades * 100
    else:
        wr = 0
    print(f"  Win rate:     {wr:.1f}%")
    print(f"  Total P&L:    ${combined_profit:.2f}")
    print(f"  Total return: {(combined_profit / BACKTEST_CAPITAL) * 100:.2f}%")
    print(f"  Avg monthly:  ${combined_profit / num_months:.2f}")


def analyze_trades(trades: List[Dict], symbol: str):
    """Analyze trade log for patterns—held duration, SL/TP distances, consecutive losses."""
    if not trades:
        print(f"\n  {symbol}: No trades to analyze")
        return

    total = len(trades)
    wins = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] == "LOSS"]
    tp = [t for t in trades if t["exit_reason"] == "TAKE_PROFIT"]
    sl = [t for t in trades if t["exit_reason"] == "STOP_LOSS"]
    long_trades = [t for t in trades if t["side"] == "LONG"]
    short_trades = [t for t in trades if t["side"] == "SHORT"]

    avg_held = sum(t["held_candles"] for t in trades) / total
    avg_held_win = sum(t["held_candles"] for t in wins) / len(wins) if wins else 0
    avg_held_loss = sum(t["held_candles"] for t in losses) / len(losses) if losses else 0
    avg_sl_dist = sum(t["sl_distance"] for t in trades) / total
    avg_tp_dist = sum(t["tp_distance"] for t in trades) / total
    avg_atr = sum(t["atr"] for t in trades) / total

    tp_candles = [t["held_candles"] for t in tp]
    sl_candles = [t["held_candles"] for t in sl]

    consec_losses = []
    streak = 0
    for t in trades:
        if t["result"] == "LOSS":
            streak += 1
        else:
            if streak > 0:
                consec_losses.append(streak)
            streak = 0
    if streak > 0:
        consec_losses.append(streak)
    max_streak = max(consec_losses) if consec_losses else 0
    avg_streak = sum(consec_losses) / len(consec_losses) if consec_losses else 0

    print(f"\n  {'='*55}")
    print(f"  📊 {symbol} — DEBUG ANALYSIS")
    print(f"  {'='*55}")
    print(f"  Total trades:  {total}")
    print(f"  Wins:          {len(wins)} ({len(wins)/total*100:.1f}%)")
    print(f"  Losses:        {len(losses)} ({len(losses)/total*100:.1f}%)")
    print(f"  TP hits:       {len(tp)} ({len(tp)/total*100:.1f}%)")
    print(f"  SL hits:       {len(sl)} ({len(sl)/total*100:.1f}%)")
    print(f"  LONG trades:   {len(long_trades)} ({len(long_trades)/total*100:.1f}%)")
    print(f"  SHORT trades:  {len(short_trades)} ({len(short_trades)/total*100:.1f}%)")
    print()
    print(f"  ⏱  CANDLE DURATION")
    print(f"  Avg held:      {avg_held:.1f} candles ({avg_held*5:.0f} min)")
    print(f"  Avg held (win): {avg_held_win:.1f} candles ({avg_held_win*5:.0f} min)")
    print(f"  Avg held (loss): {avg_held_loss:.1f} candles ({avg_held_loss*5:.0f} min)")
    if tp_candles:
        print(f"  TP range:      {min(tp_candles)}–{max(tp_candles)} candles")
    if sl_candles:
        print(f"  SL range:      {min(sl_candles)}–{max(sl_candles)} candles")
    print()
    print(f"  📐  ATR & DISTANCES")
    print(f"  Avg ATR:       ${avg_atr:.2f} ({avg_atr/avg_sl_dist*100:.1f}% of SL dist)")
    print(f"  Avg SL dist:   ${avg_sl_dist:.2f}")
    print(f"  Avg TP dist:   ${avg_tp_dist:.2f}")
    print(f"  Ratio TP/SL:   {avg_tp_dist/avg_sl_dist:.1f}x")
    print()
    print(f"  🔄  CONSECUTIVE LOSSES")
    print(f"  Max streak:    {max_streak} losses in a row")
    print(f"  Avg streak:    {avg_streak:.1f} losses")
    print(f"  Streaks:       {consec_losses}")
    print()

    sorted_losses = sorted(losses, key=lambda t: t["profit"])
    print(f"  💥  TOP 10 LARGEST LOSSES")
    for t in sorted_losses[:10]:
        print(f"    {t['side']:5s} {t['entry_ts'][:16]:16s} → {t['exit_ts'][:16]:16s} "
              f"atr=${t['atr']:.2f} sl=${t['sl_distance']:.2f} "
              f"held={t['held_candles']}c loss=${t['profit']:.2f}")

    if len(trades) >= 2:
        first_ts = datetime.fromisoformat(trades[0]["entry_ts"])
        last_ts = datetime.fromisoformat(trades[-1]["entry_ts"])
        days = max((last_ts - first_ts).total_seconds() / 86400, 1)
        print(f"\n  📅  TRADE DENSITY")
        print(f"  Period:        {first_ts.strftime('%b %d')} → {last_ts.strftime('%b %d')} ({days:.0f} days)")
        print(f"  Trades/day:    {total/days:.1f}")
        print(f"  Avg hours between trades: {24*days/total:.1f}h")

    sl_trades = [t for t in sl]
    reentries = 0
    reentries_same_side = 0
    for i in range(1, len(trades)):
        if trades[i-1]["exit_reason"] == "STOP_LOSS":
            reentries += 1
            if trades[i]["side"] == trades[i-1]["side"]:
                reentries_same_side += 1

    print(f"\n  🔁  RE-ENTRY ANALYSIS (SL → next trade)")
    print(f"  Re-entries after SL: {reentries} ({reentries/max(len(sl),1)*100:.0f}% of SL hits)")
    print(f"  Same-side re-entries: {reentries_same_side} ({reentries_same_side/max(reentries,1)*100:.0f}% of re-entries)")


async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="12-Month Rolling Backtest of ICT Strategy")
    parser.add_argument("--months", type=int, default=12,
                        help="Number of months to backtest (default 12)")
    parser.add_argument("--offset", type=int, default=None,
                        help="Run a single month at this offset (0=newest). Overrides --months.")
    parser.add_argument("--parallel", action="store_true",
                        help="Run both symbols per month in parallel")
    parser.add_argument("--capital", type=float, default=None,
                        help="Starting capital (default: 5000)")
    parser.add_argument("--symbol", type=str, default=None,
                        help="Run a single symbol only (BTCUSDT or ETHUSDT). Default: both.")
    parser.add_argument("--debug", action="store_true",
                        help="Enable detailed per-trade debug analysis")
    parser.add_argument("--spot", action="store_true",
                        help="Spot-only mode: only trade LONG signals (skip SHORT). Matches live spot executor.")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<level>{level: <8}</level> | {message}")

    today = datetime.now(timezone.utc).date()
    all_raw_results = []

    if args.offset is not None:
        # Single-month mode
        offsets = [max(0, args.offset)]
    else:
        num_months = max(args.months, 1)
        offsets = list(reversed(range(num_months)))

    print("\n" + "=" * 70)
    if args.offset is not None:
        end_date = today - timedelta(days=args.offset * 30)
        print(f"  📊 SINGLE MONTH BACKTEST — ending {end_date.strftime('%b %d, %Y')}")
    else:
        print(f"  📊 {num_months}-MONTH ROLLING BACKTEST — ICT + DemoAccount")
    # Set dynamic capital from CLI arg if provided
    global BACKTEST_CAPITAL
    if args.capital is not None:
        BACKTEST_CAPITAL = args.capital

    symbols = [args.symbol.upper()] if args.symbol else SYMBOLS
    print(f"  Capital: ${BACKTEST_CAPITAL:,.0f} | 1% risk | 1:2 RR | 5m entries")
    print(f"  Both symbols: 0.5x SL, 0min cooldown, min_score=60")
    print(f"  Symbols: {', '.join(symbols)}")
    if args.spot:
        print(f"  SPOT MODE: LONG only (SHORT signals filtered — matches live spot executor)")
    if args.debug:
        print(f"  DEBUG MODE: enabled (per-trade analysis)")
    print("=" * 70 + "\n")

    all_trade_logs: List[Dict] = []

    for month_idx, month_offset in enumerate(offsets):
        end_date = today - timedelta(days=month_offset * 30)
        before_str = end_date.isoformat()
        month_label = end_date.strftime("%Y-%m")

        if args.offset is None:
            print(f"\n{'━'*70}")
            print(f"  Month {month_idx + 1}/{len(offsets)} — "
                  f"ending {end_date.strftime('%b %d, %Y')}")
            print(f"{'━'*70}")

        if args.parallel:
            tasks = [backtest_symbol(sym, before=before_str, debug=args.debug, spot=args.spot) for sym in symbols]
            results = await asyncio.gather(*tasks)
        else:
            results = []
            for sym in symbols:
                r = await backtest_symbol(sym, before=before_str, debug=args.debug, spot=args.spot)
                results.append(r)
                print()

        r1, r2 = results[0], results[1] if len(results) > 1 else None

        labels = {s.upper(): s.upper() for s in symbols}
        dr_parts = {}
        for r in results:
            sym = r["symbol"]
            dr_parts[sym] = r.get("data_range", "") if r.get("total_trades", 0) > 0 else "(no data)"
        data_range = " | ".join(f"{k}: {v}" for k, v in dr_parts.items())

        print_month_result(month_idx + 1, month_label, data_range, r1, r2)
        all_raw_results.extend(results)

        # Collect debug trade logs
        if args.debug:
            for r in results:
                if r.get("trade_log"):
                    all_trade_logs.extend(r["trade_log"])

        if args.offset is not None:
            # Print single result as JSON for easy parsing
            summary = {
                "month_offset": args.offset,
                "month": month_label,
                "end_date": before_str,
                "results": [
                    {
                        "symbol": r["symbol"],
                        "htf_bias": r.get("htf_bias", "neutral"),
                        "trades": r["total_trades"],
                        "wins": r["wins"],
                        "losses": r["losses"],
                        "win_rate_pct": round(r.get("win_rate", 0) * 100, 1),
                        "profit": round(r.get("total_profit", 0), 2),
                        "profit_factor": r.get("profit_factor", 0),
                        "max_dd_pct": round(r.get("max_drawdown", 0) * 100, 1),
                        "avg_rr": r.get("avg_rr", 0),
                        "data_range": r.get("data_range", ""),
                    }
                    for r in results
                ],
                "combined_profit": round(sum(r.get("total_profit", 0) for r in results), 2),
            }
            print(f"\n  JSON:{json.dumps(summary)}")

    if args.offset is None:
        print_combined_summary(all_raw_results, num_months)

        print(f"\n\n{'='*70}")
        print(f"  MONTHLY BREAKDOWN")
        print(f"{'='*70}")

        print(f"\n  {'Month':<10} {'Symbol':<10} {'Trades':<8} {'WR%':<8} {'P&L':<12} "
              f"{'PF':<8} {'DD%':<8} {'RR':<8}")
        print(f"  {'─'*8:<10} {'─'*8:<10} {'─'*6:<8} {'─'*5:<8} {'─'*10:<12} "
              f"{'─'*6:<8} {'─'*5:<8} {'─'*5:<8}")

        for r in all_raw_results:
            trades = r.get("total_trades", 0)
            wr = r.get("win_rate", 0) * 100
            pnl = r.get("total_profit", 0)
            pf = r.get("profit_factor", 0)
            dd = r.get("max_drawdown", 0) * 100
            rr = r.get("avg_rr", 0)
            sym = r["symbol"]
            month = r.get("month", "?")
            print(f"  {month:<10} {sym:<10} {trades:<8} {wr:<7.1f}% "
                  f"${pnl:<9.2f} {pf:<8.2f} {dd:<7.1f}% {rr:<8.2f}")

    if args.debug and all_trade_logs:
        # Group by symbol and analyze
        from collections import defaultdict
        by_symbol = defaultdict(list)
        for t in all_trade_logs:
            by_symbol[t["symbol"]].append(t)
        for sym, logs in by_symbol.items():
            analyze_trades(logs, sym)

        # Save raw trade log to file
        filename = f"debug_trades_{'_'.join(symbols)}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, "w") as f:
            json.dump(all_trade_logs, f, indent=2, default=str)
        print(f"\n  Trade log saved to {filename}")

    print()
    print(f"  Script complete.")


if __name__ == "__main__":
    asyncio.run(main())
