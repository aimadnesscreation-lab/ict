"""
12-Month Rolling Backtest — One Month at a Time

Fetches 30 days of 5m data per month via Binance klines API (direct, no
intermediary server), drives DemoAccount candle-by-candle matching live
system logic exactly.

Runs months sequentially (oldest first → most recent) to avoid timeouts.
Each month: ~8640 candles, full ICT pipeline.

Usage:
    python backtest_binance.py              # last 12 months (ETHUSDT, Combo 521)
    python backtest_binance.py --months 6   # last 6 months
    python backtest_binance.py --symbol ETHUSDT --debug  # single symbol with per-trade analysis
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
from ict_engine.liquidity import LiquidityDetector
from ict_engine.premium_discount import PremiumDiscountDetector
from ict_engine.utils import calculate_atr
from signal_engine.combo521 import Combo521Detector
from demo_account import DemoAccount, ClosedTrade
import json

# ── Data source mapping ────────────────────────────────────────────
BINANCE_BAR_MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}

SYMBOLS = ["ETHUSDT"]
# Default capital; override with --capital <amount> (e.g. --capital 10000)
BACKTEST_CAPITAL = 5_000.0
MAX_OPEN_POSITIONS = 3

_ict_ms = MarketStructure(n=2)  # Combo 521: swing_lookback=2
_ict_fvg = FVGDetector()
_ict_liquidity = LiquidityDetector(atr_threshold=0.10)
_ict_pd = PremiumDiscountDetector()
_combo521 = Combo521Detector(
    swing_lookback=2,
    max_bars_after_sweep=20,
    min_gap_pct=0.05,
    entry_mode="proximal",
    kill_zone_only=False,
)


async def fetch_historical_data(symbol: str, bar: str, days: int,
                                 before: Optional[str] = None) -> pl.DataFrame:
    """Fetch paginated historical data from Binance REST API.

    Uses Binance klines endpoint (1000 per page). Public endpoint —
    no API key needed. Paginates, deduplicates, returns sorted Polars DataFrame.

    Args:
        symbol: ETHUSDT (or any Binance Futures symbol)
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

    end_ts: Optional[datetime] = None
    if before:
        # Replace trailing Z with +00:00 for fromisoformat compatibility
        before_clean = before.replace("Z", "+00:00")
        end_ts = datetime.fromisoformat(before_clean)

    all_candles: List[Dict] = []
    page_end = end_ts
    url = "https://fapi.binance.com/fapi/v1/klines"

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
                page_end = batch[0]["timestamp"]  # type: ignore[assignment]
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
    """Run Combo 521 ICT pipeline once on a DataFrame.

    Only computes what Combo 521 needs:
      - Market structure (swing n=2)
      - FVG detection
      - Liquidity sweeps
      - Session detection
      - Premium/discount zones

    No OB, no MSS/BOS, no HTF bias.
    """
    df = df.clone()
    df = _ict_ms.detect_swings(df)
    df = _ict_fvg.detect_fvgs(df)
    df = _ict_liquidity.detect_all(df)
    df = _ict_pd.compute_zones(df)
    # ATR needed by Combo 521 for stop-loss distance calculation
    df = df.with_columns(calculate_atr(df).alias("atr"))
    return df


def extract_combo521_signal(df_ict: pl.DataFrame, candle_idx: int,
                             symbol: str = "ETHUSDT",
                             current_price: Optional[float] = None) -> Optional[Dict]:
    """
    Detect Combo 521 signals at a given candle index.

    Uses Combo521Detector to find sweep+FVG patterns with proximal entry,
    premium/discount zone filter, and 20-bar lookback.

    Returns a single signal dict (best signal if multiple) or None.
    """
    if candle_idx < 25:  # Need enough warmup candles
        return None

    signals = _combo521.detect(df_ict, current_idx=candle_idx, symbol=symbol)
    if not signals:
        return None

    sig = signals[0]  # Take the first (most recent) signal
    sig["id"] = None

    # Override price with current market price if provided
    if current_price is not None and current_price > 0:
        sig["trigger_price"] = sig["price"]
        sig["price"] = current_price

    return sig


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


def close_position(demo, pos, exit_price, exit_reason, current_ts, fee_pct: float = 0.0):
    """Close a position and update DemoAccount state.

    If fee_pct > 0, deducts round-trip trading fees from the gross profit.
    fee_pct is the total round-trip fee as a percentage of average notional
    (e.g. 0.04 = 0.04% round-trip).
    """
    if pos.side == "LONG":
        gross_profit = (exit_price - pos.entry_price) * pos.quantity
    else:
        gross_profit = (pos.entry_price - exit_price) * pos.quantity

    # Deduct trading fees
    if fee_pct > 0:
        avg_notional = ((pos.entry_price + exit_price) / 2) * pos.quantity
        fee_amount = avg_notional * (fee_pct / 100)
    else:
        fee_amount = 0.0
    profit = gross_profit - fee_amount

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
                          fee_pct: float = 0.0,
                          sl_multiplier: float = 3.0,
                          risk_pct: float = 1.0,
                          sl_slippage_pct: float = 0.05,
                          tp_slippage_pct: float = 0.02,
                          next_candle_entry: bool = True) -> Dict:
    """Run 30-day backtest using Combo 521 strategy + DemoAccount.

    No HTF bias, no scoring, no kill zone requirements — pure
    sweep+FVG pattern detection with proximal entry and 3R TP.

    Args:
        symbol: ETHUSDT (or any Binance Futures symbol)
        chunk_size: Candles per processing chunk
        before: ISO date to end the 30-day window (default: now)
        debug: Enable per-trade debug logging and analysis
        fee_pct: Round-trip fee %% (default 0.10)
        sl_multiplier: ATR multiplier for SL (default 3.0, reduces loss severity per 5-yr optimizer)
        risk_pct: Risk per trade as %% of balance (default 1.0)
        sl_slippage_pct: SL exit slippage %% (default 0.05)
        tp_slippage_pct: TP exit slippage %% (default 0.02)
        next_candle_entry: If True, defer entry by 1 candle and use next candle's open (default True)
    """
    days = 30

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

    rows = df_5m_full.to_dicts()
    total_candles = len(rows)

    demo = DemoAccount(
        initial_balance=BACKTEST_CAPITAL, risk_per_trade_pct=risk_pct,
        max_daily_loss_pct=3.0, max_open_positions=MAX_OPEN_POSITIONS,
        sl_multiplier=sl_multiplier,
        reentry_cooldown_minutes=0,
        symbol_min_scores={symbol.upper(): 0},  # Combo 521: bypass scoring
        spot_only=False,
    )

    signals_gen = 0
    trade_log: List[Dict] = []
    current_trade_start: Dict[str, Dict] = {}
    _pending_signal: Optional[Dict] = None  # Next-candle entry: signal stored here, executed next iteration

    # Pre-compute ICT columns once
    logger.info(f"    Pre-computing ICT columns (swing_lookback=2)...")
    t_ict = datetime.now(timezone.utc)
    df_ict = precompute_ict(df_5m_full)
    ict_elapsed = (datetime.now(timezone.utc) - t_ict).total_seconds()
    logger.info(f"    ICT pre-compute: {ict_elapsed:.1f}s for {len(df_ict)} rows")

    warmup = 30  # need enough data for 20-bar lookback + safety margin
    i = warmup

    while i < total_candles:
        chunk_end = min(i + chunk_size, total_candles)
        chunk_rows = rows[i:chunk_end]

        for j, current in enumerate(chunk_rows):
            current_price = current["close"]
            current_ts = current["timestamp"]
            candle_idx = i + j

            # Step 0: Process pending signal from previous candle (next-candle-open entry)
            # Models: signal fires at candle close → market order → fills at next candle's open
            if next_candle_entry and _pending_signal is not None:
                next_open = current["open"]
                _pending_signal["price"] = next_open
                _pending_signal["trigger_price"] = next_open
                _pending_signal["timestamp"] = current_ts

                prev_positions = set(demo.open_positions.keys())
                demo.process_signals([_pending_signal], {symbol: next_open}, current_time=current_ts)
                if debug:
                    for sym in demo.open_positions.keys():
                        if sym not in prev_positions:
                            current_trade_start[sym] = {"candle_idx": candle_idx, "entry_ts": current_ts}
                _pending_signal = None

            # Step 1: Check open positions against candle H/L
            for sym in list(demo.open_positions.keys()):
                if sym != symbol:
                    continue
                pos = demo.open_positions[sym]
                reason, price = check_position_vs_candle(pos, current["high"], current["low"], current_ts)
                if reason is not None:
                    # Apply slippage to exit price
                    if sl_slippage_pct > 0 or tp_slippage_pct > 0:
                        if reason == "STOP_LOSS" and sl_slippage_pct > 0:
                            if pos.side == "LONG":
                                price = price * (1 - sl_slippage_pct / 100)
                            else:
                                price = price * (1 + sl_slippage_pct / 100)
                        elif reason == "TAKE_PROFIT" and tp_slippage_pct > 0:
                            if pos.side == "LONG":
                                price = price * (1 - tp_slippage_pct / 100)
                            else:
                                price = price * (1 + tp_slippage_pct / 100)

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
                    close_position(demo, pos, price, reason, current_ts, fee_pct=fee_pct)
                    if debug and sym in current_trade_start:
                        del current_trade_start[sym]

            # Step 2: Detect Combo 521 signal
            sig = extract_combo521_signal(df_ict, candle_idx, symbol=symbol, current_price=current_price)
            if sig is not None:
                sig["timestamp"] = current_ts
                signals_gen += 1

            # Step 3: Store signal as pending (next-candle entry) or execute immediately
            if next_candle_entry:
                _pending_signal = sig
            else:
                aligned = [sig] if sig else []
                prev_positions = set(demo.open_positions.keys())
                demo.process_signals(aligned, {symbol: current_price}, current_time=current_ts)
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

    ts_min = df_5m_full['timestamp'].min().strftime('%b %d')
    ts_max = df_5m_full['timestamp'].max().strftime('%b %d')
    data_range_str = f"{ts_min} → {ts_max}"

    result = {
        "symbol": symbol, "month": str(before or "latest"),
        "data_range": data_range_str,
        "total_trades": perf["total_trades"],
        "wins": wins, "losses": losses, "breakeven": breakeven,
        "win_rate": perf["win_rate"], "total_profit": perf["total_profit"],
        "profit_factor": perf["profit_factor"], "max_drawdown": perf["max_drawdown"],
        "avg_rr": perf["avg_rr"], "capital_remaining": perf["capital_remaining"],
        "signals_gen": signals_gen,
        "still_open": len(open_pos),
    }
    if debug:
        result["trade_log"] = trade_log
    return result


def print_month_result(month_num: int, month_label: str, data_range: str,
                       r1: Dict, r2: Optional[Dict] = None,
                       starting_cap: Optional[float] = None):
    """Print a formatted monthly result block."""
    print(f"\n  {'─'*60}")
    cap_info = f" (cap=${starting_cap:,.0f})" if starting_cap else ""
    print(f"  Month {month_num}/12 — {month_label}{cap_info}")
    print(f"  {data_range}")
    print(f"  {'─'*60}")

    results_to_print = [r for r in [r1, r2] if r is not None]
    for r in results_to_print:
        if r.get("total_trades", 0) == 0:
            print(f"  {r['symbol']}: {r.get('result', 'No trades')}")
            continue

        print(f"  {r['symbol']}  Trades: {r['total_trades']}  "
              f"W:{r['wins']} L:{r['losses']} BE:{r['breakeven']}  "
              f"Open: {r['still_open']}")
        print(f"    WR: {r['win_rate']*100:.1f}%  "
              f"PF: {r['profit_factor']:.2f}  "
              f"P&L: ${r['total_profit']:.2f}  "
              f"DD: {r['max_drawdown']*100:.1f}%  "
              f"RR: {r['avg_rr']:.2f}")


def print_combined_summary(all_results: List[Dict], num_months: int,
                            opening_capital: Optional[float] = None):
    """Print aggregated multi-month summary, grouped by symbol."""
    if opening_capital is None:
        opening_capital = BACKTEST_CAPITAL
    print(f"\n\n{'='*70}")
    print(f"  {num_months}-MONTH COMBINED SUMMARY")
    print(f"{'='*70}")

    # Group results by symbol (dynamic — works with any symbols)
    by_symbol: Dict[str, Dict] = {}
    for r in all_results:
        sym = r["symbol"]
        if sym not in by_symbol:
            by_symbol[sym] = {"trades": 0, "wins": 0, "losses": 0, "profit": 0.0,
                              "dd_sum": 0.0, "dd_count": 0, "rr_sum": 0.0, "rr_count": 0,
                              "signals_gen": 0, "signals_kept": 0}
        g = by_symbol[sym]
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

    for sym, g in by_symbol.items():
        if g["trades"] == 0:
            print(f"\n  {sym}: No trades across all months")
            continue
        wr = g["wins"] / g["trades"] * 100 if g["trades"] > 0 else 0
        avg_dd = g["dd_sum"] / g["dd_count"] * 100 if g["dd_count"] > 0 else 0
        avg_rr = g["rr_sum"] / g["rr_count"] if g["rr_count"] > 0 else 0
        print(f"\n  {sym}")
        print(f"    Total trades: {g['trades']}  (W:{g['wins']} L:{g['losses']})")
        print(f"    Win rate:     {wr:.1f}%")
        print(f"    Total P&L:    ${g['profit']:.2f}")
        print(f"    Avg DD:       {avg_dd:.1f}%")
        print(f"    Avg RR:       {avg_rr:.2f}")
        print(f"    Signals:      {g['signals_gen']} gen → {g['signals_kept']} kept")

    # Overall combined metrics across all symbols
    combined_trades = sum(g["trades"] for g in by_symbol.values())
    combined_profit = sum(g["profit"] for g in by_symbol.values())
    combined_wins = sum(g["wins"] for g in by_symbol.values())
    combined_symbols = " + ".join(by_symbol.keys())

    print(f"\n  {'─'*55}")
    print(f"  COMBINED ({combined_symbols})")
    print(f"  {'─'*55}")
    print(f"  Total trades: {combined_trades}")
    if combined_trades > 0:
        wr = combined_wins / combined_trades * 100
    else:
        wr = 0
    print(f"  Win rate:     {wr:.1f}%")
    print(f"  Total P&L:    ${combined_profit:.2f}")
    # Use opening capital for return calc (passed in as param to avoid mutated module-level var)
    final_capitals = {r["symbol"]: r.get("capital_remaining", 0) for r in all_results[-len(by_symbol):]}
    final_cap = max(final_capitals.values()) if final_capitals else 0
    if final_cap > 0 and abs(final_cap - opening_capital) > 0.01:
        print(f"  Final capital: ${final_cap:,.2f}")
        print(f"  Total return:  {(final_cap - opening_capital) / opening_capital * 100:.2f}%")
    else:
        print(f"  Total return: {(combined_profit / opening_capital) * 100:.2f}%")
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
                        help="Run symbols per month in parallel")
    parser.add_argument("--capital", type=float, default=None,
                        help="Starting capital (default: 5000)")
    parser.add_argument("--sl-slippage-pct", type=float, default=0.05,
                        help="SL exit slippage %% (default 0.05)")
    parser.add_argument("--tp-slippage-pct", type=float, default=0.02,
                        help="TP exit slippage %% (default 0.02)")
    parser.add_argument("--no-next-candle-entry", action="store_true",
                        help="Disable next-candle-open deferral — use immediate FVG edge entry (legacy mode)")
    parser.add_argument("--max-bars", type=int, default=20,
                        help="Max bars after sweep for Combo 521 (default 20)")
    parser.add_argument("--min-gap-pct", type=float, default=0.05,
                        help="Min FVG gap %% for Combo 521 (default 0.05)")
    parser.add_argument("--symbol", type=str, default=None,
                        help="Symbol to backtest (default: ETHUSDT)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable detailed per-trade debug analysis")
    parser.add_argument("--fee-pct", type=float, default=0.06,
                        help="Round-trip trading fee %% (default 0.06: 0.02%% maker entry + 0.04%% taker exit — winning config)")
    parser.add_argument("--sl-multiplier", type=float, default=3.0,
                        help="ATR multiplier for SL (default 3.0, reduces loss severity per 5-yr optimizer)")
    parser.add_argument("--entry-mode", type=str, default="immediate",
                        choices=["immediate", "next-candle"],
                        help="Entry model: 'immediate' = FVG edge fills this candle (limit order, maker fee), 'next-candle' = defer to next open (market order, taker fee) — default: immediate (winning config)")
    parser.add_argument("--risk-pct", type=float, default=1.0,
                        help="Risk per trade %% of balance (default 1.0)")
    parser.add_argument("--kill-zone-only", action="store_true",
                        help="Only trade during London (07-09 UTC) and NY (13-15 UTC) kill zones")
    parser.add_argument("--compound", action="store_true",
                        help="Compound capital across months (don't reset to initial each month)")
    args = parser.parse_args()

    # Rebuild Combo521 detector with custom params
    global _combo521
    _combo521 = Combo521Detector(
        swing_lookback=2,
        max_bars_after_sweep=args.max_bars,
        min_gap_pct=args.min_gap_pct,
        entry_mode="proximal",
        kill_zone_only=args.kill_zone_only,
    )

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
    print(f"  Capital: ${BACKTEST_CAPITAL:,.0f} | {args.risk_pct}% risk | 3R TP | 5m entries")
    print(f"  SL: {args.sl_multiplier}x ATR | 0min cooldown")
    print(f"  Strategy: Combo 521 (5m sweep+FVG, proximal entry, PD zone filter)")
    if args.kill_zone_only:
        print(f"  Kill Zone filter: Enabled (London 07-09 / NY 13-15 UTC only)")
    print(f"  Symbols: {', '.join(symbols)}")
    if args.compound:
        print(f"  Mode: COMPOUNDING (capital carries across months)")
    if args.debug:
        print(f"  DEBUG MODE: enabled (per-trade analysis)")
    if args.fee_pct > 0:
        print(f"  Fee: {args.fee_pct}% round-trip")
    print(f"  Slippage: SL={args.sl_slippage_pct}% TP={args.tp_slippage_pct}%")
    next_candle_entry = args.entry_mode == "next-candle"
    if next_candle_entry:
        print(f"  Entry: next-candle open (market order model, taker fee)")
    else:
        print(f"  Entry: immediate FVG edge (limit order model, maker fee) — default winning config")
    print("=" * 70 + "\n")

    # Save initial capital for compound mode return calculation
    initial_capital = BACKTEST_CAPITAL
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
            tasks = [backtest_symbol(sym, before=before_str, debug=args.debug, fee_pct=args.fee_pct, sl_multiplier=args.sl_multiplier, risk_pct=args.risk_pct, sl_slippage_pct=args.sl_slippage_pct, tp_slippage_pct=args.tp_slippage_pct, next_candle_entry=next_candle_entry) for sym in symbols]
            results = await asyncio.gather(*tasks)
        else:
            results = []
            for sym in symbols:
                r = await backtest_symbol(sym, before=before_str, debug=args.debug, fee_pct=args.fee_pct, sl_multiplier=args.sl_multiplier, risk_pct=args.risk_pct, sl_slippage_pct=args.sl_slippage_pct, tp_slippage_pct=args.tp_slippage_pct, next_candle_entry=next_candle_entry)
                results.append(r)
                print()

        r1, r2 = results[0], results[1] if len(results) > 1 else None

        dr_parts = {}
        for r in results:
            sym = r["symbol"]
            dr_parts[sym] = r.get("data_range", "") if r.get("total_trades", 0) > 0 else "(no data)"
        data_range = " | ".join(f"{k}: {v}" for k, v in dr_parts.items())

        print_month_result(month_idx + 1, month_label, data_range, r1, r2, starting_cap=initial_capital if not args.compound else None)
        all_raw_results.extend(results)

        # ── Compounding: carry capital forward to next month ────────
        if args.compound and args.offset is None:
            cap_remaining = r.get("capital_remaining", BACKTEST_CAPITAL)
            if cap_remaining > 0:
                BACKTEST_CAPITAL = cap_remaining
                logger.info(f"  [Compound] Capital carried forward: ${BACKTEST_CAPITAL:.2f}")

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
        print_combined_summary(all_raw_results, num_months, opening_capital=initial_capital)

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
