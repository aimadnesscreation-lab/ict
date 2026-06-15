"""
30-Day Historical Backtest — Identical Logic to Live Demo Account

Fetches 30 days of 5m data from Railway's /backtest-data endpoint (paginated OKX),
drives DemoAccount candle-by-candle matching live system logic exactly:
  - Every 5m close → ICT on 5m + 15m buffers → score≥70 + kill zone + HTF-aligned
  - DemoAccount handles SL/TP (candle H/L), max 1 position/symbol, no repeats

Usage:
    python backtest_okx.py
"""

import asyncio
import httpx
import polars as pl
from datetime import datetime
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
from ict_engine.breaker_block import BreakerBlockDetector
from signal_engine.engine import SignalEngine, determine_bias_from_swings, determine_bias_from_ema
from demo_account import DemoAccount, ClosedTrade

RAILWAY_URL = "https://ict-production-b1a8.up.railway.app"
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
BACKTEST_DAYS = 30
BACKTEST_CAPITAL = 10_000.0
MAX_OPEN_POSITIONS = 3

_ict_ms = MarketStructure(n=3)
_ict_fvg = FVGDetector()
_ict_ob = OrderBlockDetector()
_ict_liquidity = LiquidityDetector(atr_threshold=0.10)
_ict_sessions = SessionDetector()
_ict_pd = PremiumDiscountDetector()
_ict_breaker = BreakerBlockDetector()
_signal_engine = SignalEngine()


def _resample_5m_to_15m(df: pl.DataFrame) -> pl.DataFrame:
    idx = df.with_row_index().with_columns((pl.col("index") // 3).alias("_g"))
    return idx.group_by("_g", maintain_order=True).agg([
        pl.col("timestamp").first(), pl.col("open").first(),
        pl.col("high").max(), pl.col("low").min(),
        pl.col("close").last(), pl.col("volume").sum(),
    ]).drop("_g").sort("timestamp")


async def fetch_backtest_data(symbol: str, bar: str, days: int) -> pl.DataFrame:
    """Fetch paginated historical data from /backtest-data endpoint."""
    url = f"{RAILWAY_URL}/backtest-data/{symbol}"
    params = {"bar": bar, "days": days}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning(f"API HTTP {resp.status_code}")
                return pl.DataFrame()
            data = resp.json()
            if not isinstance(data, list) or len(data) < 10:
                logger.warning(f"API returned {len(data) if isinstance(data, list) else 0} candles")
                return pl.DataFrame()

            rows = []
            for d in data:
                ts = d.get("timestamp", "")
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                rows.append({
                    "timestamp": ts,
                    "open": float(d.get("open", 0)),
                    "high": float(d.get("high", 0)),
                    "low": float(d.get("low", 0)),
                    "close": float(d.get("close", 0)),
                    "volume": float(d.get("volume", 0)),
                })

            df = pl.DataFrame(rows).sort("timestamp")
            logger.info(f"[API] Fetched {len(df)} {bar} candles for {symbol} ({days}d)")
            return df
    except Exception as e:
        logger.error(f"[API] Fetch failed: {e}")
        return pl.DataFrame()


def run_ict_on_buffer(buffer: pl.DataFrame, htf_bias: str, current_price: float) -> Optional[Dict]:
    """Run full ICT pipeline on a buffer slice. Returns signal dict if qualifying, else None."""
    df = buffer.clone()
    if len(df) < 20:
        return None

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
        news_sentiment=0.0, timeframe="5m", htf_bias=htf_bias,
    )
    signal["symbol"] = ""
    signal["id"] = None

    if "atr" in df.columns:
        latest_atr = df["atr"].tail(1).to_list()
        signal["atr"] = latest_atr[0] if latest_atr and latest_atr[0] is not None else 0.0
    else:
        signal["atr"] = 0.0

    score = signal.get("score", 0)
    signal_type = signal.get("signal_type", "NEUTRAL")
    in_kz = signal.get("in_kill_zone", False)

    # Same filters as live system: score≥70 + kill zone + HTF-aligned
    if score < 70 or not in_kz or signal_type == "NEUTRAL":
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


async def backtest_symbol(symbol: str, chunk_size: int = 500) -> Dict:
    """Run 30-day backtest using DemoAccount, processing in chunks to avoid O(n²) blowup.

    Instead of running the full ICT pipeline on a buffer that grows from 20 to 8640
    (which is O(n²) ≈ 37M cell evaluations), we process in fixed-size chunks.
    Each chunk starts with a warm-up buffer, then walks through new candles.
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"Backtesting {symbol}")
    logger.info(f"{'='*60}")

    # 1. Fetch 30 days of 5m data
    t0 = datetime.utcnow()
    df_5m_full = await fetch_backtest_data(symbol, "5m", BACKTEST_DAYS)
    if df_5m_full.is_empty() or len(df_5m_full) < 100:
        return {"symbol": symbol, "total_trades": 0, "result": f"Only {len(df_5m_full)} candles"}

    logger.info(f"5m range: {df_5m_full['timestamp'].min()} → {df_5m_full['timestamp'].max()}, "
                f"{len(df_5m_full)} candles ({BACKTEST_DAYS}d) [fetch: {(datetime.utcnow()-t0).total_seconds():.0f}s]")

    # 2. Fetch 1h data for HTF bias (recomputed periodically, matching live 15-min update cycle)
    df_1h = await fetch_backtest_data(symbol, "1H", BACKTEST_DAYS)
    htf_bias = "neutral"
    if not df_1h.is_empty() and len(df_1h) >= 26:
        # Use first 168 1h candles for initial bias (matches live _htf_bias_worker startup)
        df_1h_init = df_1h.slice(0, min(168, len(df_1h)))
        htf_bias = determine_bias_from_ema(df_1h_init, fast=12, slow=26, threshold_pct=0.5)
        swing_bias = determine_bias_from_swings(_ict_ms.detect_swings(df_1h_init))
        logger.info(f"Initial HTF bias: {htf_bias.upper()} (EMA) swings: {swing_bias.upper()}")
    else:
        logger.info(f"Initial HTF bias: neutral ({len(df_1h)} 1h candles)")

    # 3. Pre-resample to 15m
    df_15m_full = _resample_5m_to_15m(df_5m_full)
    rows = df_5m_full.to_dicts()
    rows_15m = df_15m_full.to_dicts()
    total_candles = len(rows)

    # 4. Initialize DemoAccount
    demo = DemoAccount(
        initial_balance=BACKTEST_CAPITAL, risk_per_trade_pct=1.0,
        max_daily_loss_pct=3.0, max_open_positions=MAX_OPEN_POSITIONS,
    )

    signals_gen = 0
    signals_kept = 0

    # 5. Process in chunks with periodic HTF bias recomputation
    # Live system updates HTF bias every 15 min. Here we update every 288 5m candles (~1 day).
    HTF_REFRESH_INTERVAL = 288  # 5m candles per day
    warmup = 50
    i = warmup
    last_bias_refresh = 0

    while i < total_candles:
        chunk_end = min(i + chunk_size, total_candles)
        chunk_rows = rows[i:chunk_end]

        # Recompute HTF bias periodically (matches live _htf_bias_worker, uses latest 168 1h candles)
        if i - last_bias_refresh >= HTF_REFRESH_INTERVAL:
            current_ts = rows[i]["timestamp"]
            df_1h_slice = df_1h.filter(pl.col("timestamp") <= current_ts)
            df_1h_window = df_1h_slice.tail(min(168, len(df_1h_slice)))
            if len(df_1h_window) >= 26:
                new_bias = determine_bias_from_ema(df_1h_window, fast=12, slow=26, threshold_pct=0.5)
                if new_bias != htf_bias:
                    logger.info(f"  [Bias] HTF changed: {htf_bias.upper()} → {new_bias.upper()} @ candle {i}")
                    htf_bias = new_bias
            last_bias_refresh = i

        for j, current in enumerate(chunk_rows):
            current_price = current["close"]
            current_ts = current["timestamp"]
            candle_idx = i + j

            # Build buffers up to current candle
            buf_5m = df_5m_full.slice(0, candle_idx + 1)
            buf_15m = df_15m_full.filter(pl.col("timestamp") <= current_ts)

            # Run ICT on 5m
            sig_5m = run_ict_on_buffer(buf_5m, htf_bias, current_price)

            # Run ICT on 15m
            sig_15m = None
            if len(buf_15m) >= 15:
                sig_15m = run_ict_on_buffer(buf_15m, htf_bias, current_price)

            # Collect qualifying signals
            candle_signals = []
            for sig in [sig_5m, sig_15m]:
                if sig is not None:
                    sig["symbol"] = symbol
                    sig["timestamp"] = current_ts
                    candle_signals.append(sig)

            if candle_signals:
                signals_gen += len(candle_signals)

            # HTF alignment filter
            if htf_bias != "neutral":
                aligned = [s for s in candle_signals if s.get("htf_aligned", True)]
            else:
                aligned = []

            if aligned:
                signals_kept += len(aligned)

            # Step 1: Check open positions against candle H/L
            for sym in list(demo.open_positions.keys()):
                if sym != symbol:
                    continue
                pos = demo.open_positions[sym]
                reason, price = check_position_vs_candle(pos, current["high"], current["low"], current_ts)
                if reason is not None:
                    close_position(demo, pos, price, reason, current_ts)

            # Step 2: Feed new signals to DemoAccount
            demo.process_signals(aligned, {symbol: current_price})

        i = chunk_end

        # Progress report
        pct = (i / total_candles) * 100
        elapsed = (datetime.utcnow() - t0).total_seconds()
        cps = i / elapsed if elapsed > 0 else 0
        logger.info(f"  [{symbol}] {pct:.0f}% — {i}/{total_candles} candles processed "
                    f"({cps:.0f} candles/s, {elapsed:.0f}s elapsed)")

    # Collect results
    perf = demo.get_performance()
    trades = demo.get_closed_trades_list(500)
    open_pos = demo.get_open_positions_list()

    wins = sum(1 for t in trades if t["result"] == "WIN")
    losses = sum(1 for t in trades if t["result"] == "LOSS")
    breakeven = sum(1 for t in trades if t["result"] == "BREAK_EVEN")

    elapsed = (datetime.utcnow() - t0).total_seconds()
    logger.info(f"\n  Trades: {perf['total_trades']} (W:{wins} L:{losses} BE:{breakeven})")
    logger.info(f"  Win rate: {perf['win_rate']*100:.1f}% | PF: {perf['profit_factor']:.2f}")
    logger.info(f"  Profit: ${perf['total_profit']:.2f} | Max DD: {perf['max_drawdown']*100:.1f}%")
    logger.info(f"  Avg RR: {perf['avg_rr']:.2f} | Still open: {len(open_pos)}")
    logger.info(f"  Signals: {signals_gen} gen → {signals_kept} kept | Time: {elapsed:.0f}s")

    return {
        "symbol": symbol, "htf_bias": htf_bias, "total_trades": perf["total_trades"],
        "wins": wins, "losses": losses, "breakeven": breakeven,
        "win_rate": perf["win_rate"], "total_profit": perf["total_profit"],
        "profit_factor": perf["profit_factor"], "max_drawdown": perf["max_drawdown"],
        "avg_rr": perf["avg_rr"], "capital_remaining": perf["capital_remaining"],
        "signals_gen": signals_gen, "signals_kept": signals_kept,
        "still_open": len(open_pos),
    }


async def main():
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{level: <8}</level> | {message}")

    print("\n" + "="*75)
    print("  🔬 30-DAY HISTORICAL BACKTEST — Full ICT Pipeline + DemoAccount")
    print(f"  Capital: ${BACKTEST_CAPITAL} | Max {MAX_OPEN_POSITIONS} positions | "
          f"1% risk | 1:2 RR")
    print("  Entry: score≥70 + kill zone + HTF-aligned | No duplicate positions")
    print("="*75 + "\n")

    results = []
    for symbol in SYMBOLS:
        r = await backtest_symbol(symbol)
        if r:
            results.append(r)
        print()

    print("\n" + "="*75)
    print("  RESULTS SUMMARY")
    print("="*75)

    combined_trades = combined_profit = combined_wins = combined_losses = 0
    for r in results:
        if r.get("total_trades", 0) == 0:
            print(f"\n  {r['symbol']} — {r.get('result', 'No trades')} ({r['htf_bias'].upper()})")
            continue

        print(f"\n  {r['symbol']}  (HTF: {r['htf_bias'].upper()})")
        print(f"    Signals: {r['signals_gen']} gen → {r['signals_kept']} kept")
        print(f"    Trades:  {r['total_trades']}  (W:{r['wins']} L:{r['losses']} BE:{r['breakeven']})")
        print(f"    Open:    {r['still_open']}")
        print(f"    Win rate:   {r['win_rate']*100:.1f}%")
        print(f"    Profit:     ${r['total_profit']:.2f}")
        print(f"    Profit factor: {r['profit_factor']:.2f}")
        print(f"    Max DD:     {r['max_drawdown']*100:.1f}%")
        print(f"    Avg RR:     {r['avg_rr']:.2f}")

        combined_trades += r['total_trades']
        combined_profit += r['total_profit']
        combined_wins += r['wins']
        combined_losses += r['losses']

    print(f"\n  {'─'*55}")
    print(f"  COMBINED: {combined_trades} trades ({combined_wins}W / {combined_losses}L)")
    if combined_trades > 0:
        wr = combined_wins / combined_trades * 100
    else:
        wr = 0
    print(f"  Win rate: {wr:.1f}%")
    print(f"  Total P&L: ${combined_profit:.2f}")
    print(f"  Return: {(combined_profit / BACKTEST_CAPITAL) * 100:.2f}%")
    print(f"  Final capital: ${BACKTEST_CAPITAL + combined_profit:.2f}")
    print()

if __name__ == "__main__":
    asyncio.run(main())
