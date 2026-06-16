"""
Debug Backtest — Per-Trade Analysis

Captures every trade with full metadata to diagnose:
- Why ETH gets 2× trades vs BTC
- Why win rate is so low
- Whether SL is being hit too quickly
- Whether consecutive same-direction trades are the problem

Usage:
    python debug_backtest.py          # runs July 2025 (worst month for ETH)
    python debug_backtest.py --offset 2   # different month
"""

import asyncio
import httpx
import polars as pl
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from loguru import logger
import sys
import os
import json

sys.path.insert(0, os.path.dirname(__file__))

from ict_engine.market_structure import MarketStructure
from ict_engine.fvg import FVGDetector
from ict_engine.order_blocks import OrderBlockDetector
from ict_engine.liquidity import LiquidityDetector
from ict_engine.sessions import SessionDetector
from ict_engine.premium_discount import PremiumDiscountDetector
from ict_engine.breaker_block import BreakerBlockDetector
from signal_engine.engine import SignalEngine, determine_bias_from_ema
from demo_account import DemoAccount, ClosedTrade

RAILWAY_URL = "https://ict-production-b1a8.up.railway.app"
BACKTEST_CAPITAL = 10_000.0

_ict_ms = MarketStructure(n=3)
_ict_fvg = FVGDetector()
_ict_ob = OrderBlockDetector()
_ict_liquidity = LiquidityDetector(atr_threshold=0.10)
_ict_sessions = SessionDetector()
_ict_pd = PremiumDiscountDetector()
_ict_breaker = BreakerBlockDetector()
_signal_engine = SignalEngine()


async def fetch_data(symbol: str, bar: str, days: int = 30,
                     before: Optional[str] = None) -> pl.DataFrame:
    url = f"{RAILWAY_URL}/backtest-data/{symbol}"
    params = {"bar": bar, "days": days}
    if before:
        params["before"] = before
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            return pl.DataFrame()
        data = resp.json()
        if not isinstance(data, list) or len(data) < 10:
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
        return pl.DataFrame(rows).sort("timestamp")


def run_ict_on_buffer(buffer: pl.DataFrame, htf_bias: str, current_price: float,
                       min_score: int = 70) -> Optional[Dict]:
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
        timeframe="5m", htf_bias=htf_bias,
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

    # Per-symbol score threshold + KZ + cooldown
    if score < min_score or not in_kz or signal_type == "NEUTRAL":
        return None
    if htf_bias != "neutral" and not signal.get("htf_aligned", True):
        return None

    signal["price"] = current_price
    return signal


async def debug_backtest_symbol(symbol: str, before: Optional[str] = None) -> Dict:
    """Run backtest with detailed per-trade logging."""
    logger.info(f"\n{'='*60}")
    logger.info(f"DEBUG BACKTEST — {symbol}")
    logger.info(f"{'='*60}")

    t0 = datetime.utcnow()
    df_5m = await fetch_data(symbol, "5m", 30, before=before)
    if df_5m.is_empty() or len(df_5m) < 100:
        return {"symbol": symbol, "error": f"Only {len(df_5m)} candles"}

    df_1h = await fetch_data(symbol, "1H", 30, before=before)

    htf_bias = "neutral"
    if not df_1h.is_empty() and len(df_1h) >= 26:
        df_1h_init = df_1h.slice(0, min(168, len(df_1h)))
        htf_bias = determine_bias_from_ema(df_1h_init, fast=12, slow=26, threshold_pct=0.5)

    logger.info(f"HTF bias: {htf_bias.upper()} | Candles: {len(df_5m)}")

    rows = df_5m.to_dicts()
    total = len(rows)

    sl_mult = 0.5  # 0.5× ATR for all symbols
    demo = DemoAccount(initial_balance=BACKTEST_CAPITAL, risk_per_trade_pct=1.0,
                       max_daily_loss_pct=3.0, max_open_positions=3,
                       sl_multiplier=sl_mult,
                       reentry_cooldown_minutes=60,
                       symbol_min_scores={symbol.upper(): 80})

    MAX_5M = 288
    HTF_REFRESH = 288
    warmup = 50
    chunk_size = 500

    # Track per-trade debug info
    trade_log = []      # metadata about each trade as it opens
    current_trade_start = {}  # symbol -> {candle_idx, signal_type, score, tf, atr, price}

    sig_gen = sig_keep = 0
    i = warmup
    last_bias_refresh = 0

    while i < total:
        chunk_end = min(i + chunk_size, total)
        chunk_rows = rows[i:chunk_end]

        if i - last_bias_refresh >= HTF_REFRESH:
            ts = rows[i]["timestamp"]
            df_1h_slice = df_1h.filter(pl.col("timestamp") <= ts)
            df_1h_win = df_1h_slice.tail(min(168, len(df_1h_slice)))
            if len(df_1h_win) >= 26:
                nb = determine_bias_from_ema(df_1h_win, fast=12, slow=26, threshold_pct=0.5)
                if nb != htf_bias:
                    logger.info(f"  Bias: {htf_bias.upper()} → {nb.upper()}")
                    htf_bias = nb
            last_bias_refresh = i

        for j, cur in enumerate(chunk_rows):
            cur_price = cur["close"]
            cur_ts = cur["timestamp"]
            idx = i + j

            # Track trade start candle
            for sym in list(demo.open_positions.keys()):
                if sym not in current_trade_start:
                    current_trade_start[sym] = {"candle_idx": idx, "entry_ts": cur_ts}

            # Run ICT on 5m buffer every candle for real-time entries
            aligned = []
            buf_start = max(0, idx - MAX_5M) if idx > MAX_5M else 0
            buf = df_5m.slice(buf_start, idx - buf_start)
            if len(buf) >= 15:
                sig = run_ict_on_buffer(buf, htf_bias, cur_price)
                if sig is not None:
                    sig["symbol"] = symbol
                    sig["timestamp"] = cur_ts
                    sig_gen += 1

                    if htf_bias != "neutral":
                        if sig.get("htf_aligned", True):
                            aligned = [sig]
                            sig_keep += 1
                    else:
                        aligned = []

            # Check SL/TP via H/L
            for sym in list(demo.open_positions.keys()):
                if sym != symbol:
                    continue
                pos = demo.open_positions[sym]
                # Check H/L
                exit_reason, exit_price = None, None
                if pos.side == "LONG":
                    if cur["high"] >= pos.take_profit:
                        exit_reason, exit_price = "TAKE_PROFIT", pos.take_profit
                    elif cur["low"] <= pos.stop_loss:
                        exit_reason, exit_price = "STOP_LOSS", pos.stop_loss
                else:
                    if cur["low"] <= pos.take_profit:
                        exit_reason, exit_price = "TAKE_PROFIT", pos.take_profit
                    elif cur["high"] >= pos.stop_loss:
                        exit_reason, exit_price = "STOP_LOSS", pos.stop_loss

                if exit_reason is not None:
                    held_candles = idx - current_trade_start.get(sym, {}).get("candle_idx", idx)
                    trade_log.append({
                        "symbol": pos.symbol,
                        "side": pos.side,
                        "signal_type": pos.signal_type,
                        "atr": round(pos.atr, 4),
                        "entry_price": round(pos.entry_price, 2),
                        "exit_price": round(exit_price, 2),
                        "stop_loss": round(pos.stop_loss, 2),
                        "take_profit": round(pos.take_profit, 2),
                        "sl_distance": round(abs(pos.entry_price - pos.stop_loss), 2),
                        "tp_distance": round(abs(pos.take_profit - pos.entry_price), 2),
                        "profit": round(((exit_price - pos.entry_price) * pos.quantity
                                          if pos.side == "LONG"
                                          else (pos.entry_price - exit_price) * pos.quantity), 2),
                        "result": "WIN" if ((exit_price - pos.entry_price) * pos.quantity
                                             if pos.side == "LONG"
                                             else (pos.entry_price - exit_price) * pos.quantity) > 0 else "LOSS",
                        "exit_reason": exit_reason,
                        "held_candles": held_candles,
                        "entry_ts": pos.entry_time.isoformat(),
                        "exit_ts": cur_ts.isoformat(),
                    })
                    # Record stop loss for cooldown tracking
                    if exit_reason == "STOP_LOSS":
                        demo._last_sl[pos.symbol] = {"time": cur_ts, "side": pos.side}

                    # Close position
                    if pos.side == "LONG":
                        profit = (exit_price - pos.entry_price) * pos.quantity
                    else:
                        profit = (pos.entry_price - exit_price) * pos.quantity
                    demo.balance += profit
                    demo._daily_pnl += profit
                    if demo.balance > demo._peak_balance:
                        demo._peak_balance = demo.balance
                    rr = abs(exit_price - pos.entry_price) / abs(pos.entry_price - pos.stop_loss)
                    trade = ClosedTrade(
                        symbol=pos.symbol, signal_type=pos.signal_type, side=pos.side,
                        entry_time=pos.entry_time, exit_time=cur_ts,
                        entry_price=pos.entry_price, exit_price=exit_price,
                        stop_loss=pos.stop_loss, take_profit=pos.take_profit,
                        quantity=pos.quantity, profit=profit,
                        profit_pct=0, rr=round(rr, 2), result=pos.side,
                        exit_reason=exit_reason,
                    )
                    demo.closed_trades.append(trade)
                    del demo.open_positions[pos.symbol]
                    del current_trade_start[sym]

            demo.process_signals(aligned, {symbol: cur_price}, current_time=cur_ts)

            # Track new trade start candle
            for sym in demo.open_positions.keys():
                if sym not in current_trade_start:
                    current_trade_start[sym] = {"candle_idx": idx, "entry_ts": cur_ts}

        i = chunk_end

    perf = demo.get_performance()
    logger.info(f"\n  Results: {perf['total_trades']} trades | "
                f"WR: {perf['win_rate']*100:.1f}% | "
                f"P&L: ${perf['total_profit']:.2f} | "
                f"PF: {perf['profit_factor']:.2f}")

    return {
        "symbol": symbol,
        "htf_bias": htf_bias,
        "perf": perf,
        "trades": trade_log,
        "sig_gen": sig_gen,
        "sig_keep": sig_keep,
    }


def analyze_trades(trades: List[Dict], symbol: str):
    """Analyze trade log for patterns."""
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

    # Consecutive same-direction analysis
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

    # Top 10 biggest losses
    sorted_losses = sorted(losses, key=lambda t: t["profit"])
    print(f"  💥  TOP 10 LARGEST LOSSES")
    for t in sorted_losses[:10]:
        print(f"    {t['side']:5s} {t['entry_ts'][:16]:16s} → {t['exit_ts'][:16]:16s} "
              f"atr=${t['atr']:.2f} sl=${t['sl_distance']:.2f} "
              f"held={t['held_candles']}c loss=${t['profit']:.2f}")

    # Trade density: trades per day
    if len(trades) >= 2:
        first_ts = datetime.fromisoformat(trades[0]["entry_ts"])
        last_ts = datetime.fromisoformat(trades[-1]["entry_ts"])
        days = max((last_ts - first_ts).total_seconds() / 86400, 1)
        print(f"\n  📅  TRADE DENSITY")
        print(f"  Period:        {first_ts.strftime('%b %d')} → {last_ts.strftime('%b %d')} ({days:.0f} days)")
        print(f"  Trades/day:    {total/days:.1f}")
        print(f"  Avg hours between trades: {24*days/total:.1f}h")

    # SL-hit-to-reentry analysis
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=11,
                        help="Month offset (0=newest, 11=oldest)")
    parser.add_argument("--symbol", type=str, default="ETHUSDT",
                        help="Symbol to debug")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<level>{level: <8}</level> | {message}")

    today = datetime.utcnow().date()
    end_date = today - timedelta(days=args.offset * 30)
    before_str = end_date.isoformat()

    print(f"\n{'='*70}")
    print(f"  🔬 DEBUG BACKTEST — {args.symbol} ending {end_date.strftime('%b %d, %Y')}")
    print(f"{'='*70}")

    result = await debug_backtest_symbol(args.symbol, before=before_str)

    if "error" in result:
        print(f"\n  Error: {result['error']}")
        return

    analyze_trades(result["trades"], args.symbol)

    print(f"\n  Signal efficiency: {result['sig_gen']} generated → {result['sig_keep']} kept")
    print(f"  Final balance: ${result['perf']['capital_remaining']:.2f}")
    print()

    # Save raw trade log to file
    filename = f"debug_trades_{args.symbol}_{args.offset}.json"
    with open(filename, "w") as f:
        json.dump(result["trades"], f, indent=2, default=str)
    print(f"  Trade log saved to {filename}")


if __name__ == "__main__":
    asyncio.run(main())
