"""
Combo 521 Strategy — 5-Year Backtest

Strategy Parameters:
  premium_discount=True      Use premium/discount zones for entry
  require_htf_bias=False     No higher timeframe filter
  swing_lookback=2           Swing detection: N=2
  max_bars_after_sweep=20    Enter only within 20 bars of a liquidity sweep
  fvg.min_gap_pct=0.05       Minimum FVG gap as %% of price
  entry_mode=proximal        Enter at proximal edge of the FVG
  atr=True                   Use ATR for stop-loss distance
  take_profit=fixed_r        Fixed R-multiple take profit
  fixed_r=3.0                3:1 reward-to-risk

Signal Logic:
  1. A liquidity sweep occurs (bullish = low taken/reclaimed, bearish = high taken/reclaimed)
  2. Within max_bars_after_sweep, a same-direction FVG forms with gap >= min_gap_pct
  3. When price later returns to the proximal edge of that FVG → enter
  4. LONG: bullish sweep + bullish FVG, entry at FVG_top (proximal), discount zone
  5. SHORT: bearish sweep + bearish FVG, entry at FVG_bottom (proximal), premium zone
  6. SL = ATR × sl_multiplier
  7. TP = fixed_r × SL (3R)
  8. No kill zone, no HTF bias

Usage:
    python backtest_strategy_521.py                    # Full 5 years
    python backtest_strategy_521.py --months 12        # Last 12 months
    python backtest_strategy_521.py --months 1 --debug # Debug single month
"""

import asyncio
import httpx
import polars as pl
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from loguru import logger
import sys
import os
import math

sys.path.insert(0, os.path.dirname(__file__))

from ict_engine.market_structure import MarketStructure
from ict_engine.fvg import FVGDetector
from ict_engine.liquidity import LiquidityDetector
from ict_engine.premium_discount import PremiumDiscountDetector
from ict_engine.utils import calculate_atr

# ── Strategy Parameters ────────────────────────────────────────────────
SWING_LOOKBACK = 2
MAX_BARS_AFTER_SWEEP = 20
FVG_MIN_GAP_PCT = 0.05
ENTRY_MODE = "proximal"
FIXED_R = 3.0
SL_MULTIPLIER = 3.0  # ATR multiplier for stop-loss distance (3.0x reduces loss severity per 5-yr optimizer)
RISK_PER_TRADE_PCT = 1.0
MAX_OPEN_POSITIONS = 3
INITIAL_CAPITAL = 5000.0
MAX_DAILY_LOSS_PCT = 3.0
FEE_PCT = 0.10  # Binance Futures round-trip fee: 0.05% taker entry + 0.05% taker exit

SYMBOL = "ETHUSDT"

# ── Binance API ────────────────────────────────────────────────────────
BINANCE_BAR_MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}

# ── ICT Detectors ──────────────────────────────────────────────────────
_ict_ms = MarketStructure(n=SWING_LOOKBACK)
_ict_fvg = FVGDetector()
_ict_liquidity = LiquidityDetector(atr_threshold=0.10)


# ── Data Structures ─────────────────────────────────────────────────────

@dataclass
class OpenPosition:
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_time: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: float
    risk_amount: float
    atr_value: float
    fvg_top: float
    fvg_bottom: float
    sweep_price: float
    entry_bar_index: int


@dataclass
class ClosedTrade:
    symbol: str
    side: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    quantity: float
    profit: float
    profit_pct: float
    rr: float
    result: str  # "WIN", "LOSS", "BREAK_EVEN"
    exit_reason: str  # "TAKE_PROFIT", "STOP_LOSS"
    held_candles: int
    atr_value: float
    fvg_gap_pct: float


# ── Data Fetching ───────────────────────────────────────────────────────

async def fetch_historical_data(symbol: str, bar: str, days: int,
                                 before: Optional[str] = None) -> pl.DataFrame:
    """Fetch paginated historical data from Binance REST API."""
    interval = BINANCE_BAR_MAP.get(bar)
    if not interval:
        return pl.DataFrame()

    per_day = {"1m": 720, "5m": 288, "15m": 96, "1H": 24, "4H": 6, "1D": 1}.get(bar, 288)
    total_needed = days * per_day

    end_ts: Optional[datetime] = None
    if before:
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
                page_end = batch[0]["timestamp"]
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


# ── Pre-compute ICT columns ─────────────────────────────────────────────

def precompute_ict(df: pl.DataFrame) -> pl.DataFrame:
    """Run ICT modules needed for Combo 521 on the DataFrame.

    Lookahead note: swing detection uses center=True (2-bar lookahead for
    n=2). This is a minor bias that slightly favors the strategy. The sweep
    detection itself has no lookahead (uses shift(1) + forward_fill).
    Premium/discount zones are computed from forward-filled swings below,
    eliminating end-of-dataset lookahead.
    """
    df = df.clone()

    # 1. ATR (rolling mean, backward-looking)
    df = df.with_columns(calculate_atr(df).alias("atr"))

    # 2. Swing detection (center=True — 2-bar lookahead for n=2)
    df = _ict_ms.detect_swings(df)

    # 3. FVG detection (uses shift(2) — backward-looking)
    df = _ict_fvg.detect_fvgs(df)

    # 4. Liquidity sweeps (uses shift(1) + forward_fill — backward-looking)
    df = _ict_liquidity.detect_liquidity_sweeps(df)

    # 5. Premium/discount zones from FORWARD-FILLED swings only (no lookahead)
    df = df.with_columns([
        pl.col("swing_high").forward_fill().alias("swing_high_ff"),
        pl.col("swing_low").forward_fill().alias("swing_low_ff"),
    ])
    # Compute zones using forward-filled levels as if they were the raw swings
    tmp = df.clone().with_columns([
        pl.col("swing_high_ff").alias("swing_high"),
        pl.col("swing_low_ff").alias("swing_low"),
    ])
    tmp = _ict_pd.compute_zones(tmp)
    # Copy zone columns back
    for col in ["equilibrium", "zone", "ote_62", "ote_705", "ote_79", "in_ote", "in_discount"]:
        if col in tmp.columns:
            df = df.with_columns(tmp[col].alias(col))
        else:
            df = df.with_columns(pl.lit(None).alias(col))

    return df


_ict_pd = PremiumDiscountDetector()  # initialized after precompute_ict references it


# ── Signal Detection ────────────────────────────────────────────────────

def find_active_signals(
    df_ict: pl.DataFrame,
    candle_idx: int,
    lookback: int = MAX_BARS_AFTER_SWEEP,
    min_gap_pct: float = FVG_MIN_GAP_PCT,
) -> List[Dict]:
    """
    Look back up to `lookback` candles from `candle_idx` for sweep + FVG combos.

    Returns signals where:
      - A sweep occurred, then a same-direction FVG formed
      - The FVG is not yet filled
      - Price is currently trading at the proximal edge of the FVG
      - Price is in the correct premium/discount zone
    """
    start = max(lookback + 2, candle_idx - lookback)
    if start >= candle_idx:
        return []

    window = df_ict.slice(start, candle_idx - start)
    if len(window) < 3:
        return []

    window_dicts = window.to_dicts()

    # Collect sweeps in window
    sweeps = []
    for rel_idx, row in enumerate(window_dicts):
        stype = row.get("liquidity_sweep_type")
        if stype in ("BULLISH", "BEARISH"):
            sweeps.append({
                "idx": start + rel_idx,
                "type": stype,
                "price": row.get("liquidity_sweep_price", 0),
            })

    if not sweeps:
        return []

    # Collect FVGs in window with gap >= min_gap_pct
    fvgs = []
    for rel_idx, row in enumerate(window_dicts):
        ftype = row.get("fvg_type")
        if ftype in ("BULLISH", "BEARISH"):
            top = row.get("fvg_top", 0) or 0
            bottom = row.get("fvg_bottom", 0) or 0
            if top > 0 and bottom > 0:
                gap_pct = (top - bottom) / bottom * 100
                if gap_pct >= min_gap_pct:
                    fvgs.append({
                        "idx": start + rel_idx,
                        "type": ftype, "top": top, "bottom": bottom,
                        "gap_pct": gap_pct,
                    })

    if not fvgs:
        return []

    # Current candle data
    crow = df_ict.row(candle_idx, named=True)
    curr_high = crow.get("high", 0)
    curr_low = crow.get("low", 0)
    atr = crow.get("atr", 0) or 0
    in_discount = crow.get("in_discount", False)
    if in_discount is None:
        in_discount = False

    # Match sweeps → same-direction FVGs that formed after the sweep
    signals = []
    for sw in sweeps:
        for fvg in fvgs:
            if fvg["idx"] <= sw["idx"]:
                continue
            if fvg["type"] != sw["type"]:
                continue

            # Check FVG not yet filled (price hasn't fully gone through)
            filled = _is_fvg_filled(df_ict, fvg, candle_idx)
            if filled:
                continue

            # Check price at proximal edge
            if fvg["type"] == "BULLISH":
                prox = fvg["top"]
                # Price touches the FVG top from above (retest)
                if not (curr_low <= prox * 1.001 and curr_high >= prox * 0.999):
                    continue
                entry_price = prox
            else:
                prox = fvg["bottom"]
                if not (curr_low <= prox * 1.001 and curr_high >= prox * 0.999):
                    continue
                entry_price = prox

            # Premium/discount zone filter
            if fvg["type"] == "BULLISH" and not in_discount:
                continue  # LONG needs discount
            if fvg["type"] == "BEARISH" and in_discount:
                continue  # SHORT needs premium

            signals.append({
                "side": "LONG" if fvg["type"] == "BULLISH" else "SHORT",
                "entry_price": entry_price,
                "fvg_top": fvg["top"],
                "fvg_bottom": fvg["bottom"],
                "sweep_price": sw["price"],
                "fvg_idx": fvg["idx"],
                "sweep_idx": sw["idx"],
                "gap_pct": fvg["gap_pct"],
                "atr": atr,
            })

    return signals


def _is_fvg_filled(df_ict: pl.DataFrame, fvg: Dict, candle_idx: int) -> bool:
    """Check if an FVG has been fully filled (price passed through)."""
    start = fvg["idx"]
    length = candle_idx - start + 1
    if length < 1:
        return False
    seg = df_ict.slice(start, length)
    if fvg["type"] == "BULLISH":
        # Bullish FVG: bottom = high[i-2], top = low[i]
        # Filled when price drops below bottom
        return seg["low"].min() <= fvg["bottom"]
    else:
        # Bearish FVG: bottom = high[i], top = low[i-2]
        # Filled when price rises above top
        return seg["high"].max() >= fvg["top"]


# ── Backtest per-month ──────────────────────────────────────────────────

async def backtest_month(
    symbol: str,
    before: Optional[str] = None,
    debug: bool = False,
    fee_pct: float = FEE_PCT,
    sl_multiplier: float = SL_MULTIPLIER,
    sl_slippage_pct: float = 0.05,
    tp_slippage_pct: float = 0.02,
    next_candle_entry: bool = True,
    risk_pct: float = RISK_PER_TRADE_PCT,
) -> Dict:
    """Run Combo 521 backtest on 30 days of 5m data."""

    days = 30
    t0 = datetime.now(timezone.utc)

    df_5m = await fetch_historical_data(symbol, "5m", days, before=before)
    if df_5m.is_empty() or len(df_5m) < 100:
        return {"symbol": symbol, "month": str(before or "latest"),
                "total_trades": 0, "total_profit": 0,
                "result": f"Only {len(df_5m)} candles"}

    data_range = f"{df_5m['timestamp'].min().strftime('%b %d')} → " \
                 f"{df_5m['timestamp'].max().strftime('%b %d')}"
    logger.info(f"  Range: {data_range}, {len(df_5m)} candles "
                f"[fetch: {(datetime.now(timezone.utc)-t0).total_seconds():.0f}s]")

    rows = df_5m.to_dicts()
    total_candles = len(rows)

    logger.info(f"    Pre-computing ICT columns (swing_lookback={SWING_LOOKBACK})...")
    t_ict = datetime.now(timezone.utc)
    df_ict = precompute_ict(df_5m)
    ict_elapsed = (datetime.now(timezone.utc) - t_ict).total_seconds()
    logger.info(f"    ICT pre-compute: {ict_elapsed:.1f}s for {len(df_ict)} rows")

    # State
    balance = INITIAL_CAPITAL
    peak_balance = INITIAL_CAPITAL
    open_positions: Dict[str, OpenPosition] = {}
    closed_trades: List[ClosedTrade] = []
    daily_pnl = 0.0
    last_trade_date = rows[0]["timestamp"].date() if rows else datetime.now(timezone.utc).date()

    warmup = max(50, MAX_BARS_AFTER_SWEEP + 5)
    _pending_signal: Optional[Dict] = None

    for i in range(warmup, total_candles):
        cur = rows[i]
        cur_price = cur["close"]
        cur_high = cur["high"]
        cur_low = cur["low"]
        cur_ts = cur["timestamp"]
        today = cur_ts.date()

        # Daily P&L reset
        if today != last_trade_date:
            daily_pnl = 0.0
            last_trade_date = today

        # Step 0: Process pending signal from previous candle (next-candle-open entry)
        # Models: signal fires at candle close → market order → fills at next candle's open
        if next_candle_entry and _pending_signal is not None:
            next_open = cur["open"]
            _pending_signal["entry_price"] = next_open

            sig = _pending_signal
            sym = symbol
            if sym not in open_positions:
                side = sig["side"]
                entry_price = next_open
                atr = sig.get("atr", 0) or entry_price * 0.005

                sl_dist = atr * sl_multiplier
                tp_dist = sl_dist * FIXED_R

                if side == "LONG":
                    sl = entry_price - sl_dist
                    tp = entry_price + tp_dist
                else:
                    sl = entry_price + sl_dist
                    tp = entry_price - tp_dist

                risk_unit = abs(entry_price - sl)
                if risk_unit > 0:
                    risk_amt = balance * (risk_pct / 100)
                    qty = risk_amt / risk_unit

                    open_positions[sym] = OpenPosition(
                        symbol=sym, side=side,
                        entry_time=cur_ts, entry_price=entry_price,
                        stop_loss=sl, take_profit=tp,
                        quantity=qty, risk_amount=risk_amt,
                        atr_value=atr,
                        fvg_top=sig.get("fvg_top", 0), fvg_bottom=sig.get("fvg_bottom", 0),
                        sweep_price=sig.get("sweep_price", 0), entry_bar_index=i,
                    )

                    if debug:
                        logger.info(f"  [{sym}] Pending Opened {side} @ ${entry_price:.2f} SL=${sl:.2f} TP=${tp:.2f} "
                                    f"qty={qty:.4f} risk=${risk_amt:.2f}")
            _pending_signal = None

        # ── Check open positions ──────────────────────────────────────
        for sym in list(open_positions.keys()):
            pos = open_positions[sym]
            exit_reason = None
            exit_price = None

            if pos.side == "LONG":
                if cur_high >= pos.take_profit:
                    exit_reason = "TAKE_PROFIT"
                    exit_price = pos.take_profit
                elif cur_low <= pos.stop_loss:
                    exit_reason = "STOP_LOSS"
                    exit_price = pos.stop_loss
            else:
                if cur_low <= pos.take_profit:
                    exit_reason = "TAKE_PROFIT"
                    exit_price = pos.take_profit
                elif cur_high >= pos.stop_loss:
                    exit_reason = "STOP_LOSS"
                    exit_price = pos.stop_loss

            if exit_reason and exit_price:
                # Apply slippage to exit price
                if sl_slippage_pct > 0 or tp_slippage_pct > 0:
                    if exit_reason == "STOP_LOSS" and sl_slippage_pct > 0:
                        if pos.side == "LONG":
                            exit_price = exit_price * (1 - sl_slippage_pct / 100)
                        else:
                            exit_price = exit_price * (1 + sl_slippage_pct / 100)
                    elif exit_reason == "TAKE_PROFIT" and tp_slippage_pct > 0:
                        if pos.side == "LONG":
                            exit_price = exit_price * (1 - tp_slippage_pct / 100)
                        else:
                            exit_price = exit_price * (1 + tp_slippage_pct / 100)

                profit = ((exit_price - pos.entry_price) * pos.quantity) if pos.side == "LONG" \
                    else ((pos.entry_price - exit_price) * pos.quantity)

                if fee_pct > 0:
                    avg_notional = ((pos.entry_price + exit_price) / 2) * pos.quantity
                    profit -= avg_notional * (fee_pct / 100)

                rr = abs(exit_price - pos.entry_price) / abs(pos.entry_price - pos.stop_loss) \
                    if abs(pos.entry_price - pos.stop_loss) > 0 else 0
                result = "WIN" if profit > 0 else ("LOSS" if profit < 0 else "BREAK_EVEN")

                balance += profit
                daily_pnl += profit
                if balance > peak_balance:
                    peak_balance = balance

                held = i - pos.entry_bar_index
                closed_trades.append(ClosedTrade(
                    symbol=sym, side=pos.side,
                    entry_time=pos.entry_time, exit_time=cur_ts,
                    entry_price=pos.entry_price, exit_price=exit_price,
                    stop_loss=pos.stop_loss, take_profit=pos.take_profit,
                    quantity=pos.quantity, profit=profit,
                    profit_pct=profit / (pos.entry_price * pos.quantity) if pos.entry_price > 0 and pos.quantity > 0 else 0,
                    rr=round(rr, 2), result=result, exit_reason=exit_reason,
                    held_candles=held, atr_value=pos.atr_value,
                    fvg_gap_pct=abs(pos.fvg_top - pos.fvg_bottom) / pos.fvg_bottom * 100 if pos.fvg_bottom > 0 else 0,
                ))
                del open_positions[sym]

                if debug:
                    logger.info(f"  [{sym}] Closed {pos.side}: {result} profit=${profit:.2f} RR={rr:.2f} ({exit_reason}) held={held}c")

        # ── Risk & position limits ────────────────────────────────────
        if daily_pnl <= -(INITIAL_CAPITAL * MAX_DAILY_LOSS_PCT / 100):
            continue
        if len(open_positions) >= MAX_OPEN_POSITIONS:
            continue

        # ── Detect new signals ────────────────────────────────────────
        signals = find_active_signals(df_ict, i, lookback=MAX_BARS_AFTER_SWEEP, min_gap_pct=FVG_MIN_GAP_PCT)

        if not signals:
            continue

        sig = signals[0]
        sym = symbol
        if sym in open_positions:
            continue

        if next_candle_entry:
            # Store signal as pending — will execute at next candle's open
            _pending_signal = sig
            if debug:
                logger.info(f"  [{sym}] Pending {sig['side']} @ ${sig['entry_price']:.2f} (will execute at next candle open)")
        else:
            # Execute immediately (original immediate entry behavior)
            side = sig["side"]
            entry_price = sig["entry_price"]
            atr = sig["atr"] or entry_price * 0.005  # fallback 0.5%

            sl_dist = atr * sl_multiplier
            tp_dist = sl_dist * FIXED_R

            if side == "LONG":
                sl = entry_price - sl_dist
                tp = entry_price + tp_dist
            else:
                sl = entry_price + sl_dist
                tp = entry_price - tp_dist

            risk_unit = abs(entry_price - sl)
            if risk_unit <= 0:
                continue

            risk_amt = balance * (risk_pct / 100)
            qty = risk_amt / risk_unit

            open_positions[sym] = OpenPosition(
                symbol=sym, side=side,
                entry_time=cur_ts, entry_price=entry_price,
                stop_loss=sl, take_profit=tp,
                quantity=qty, risk_amount=risk_amt,
                atr_value=atr,
                fvg_top=sig["fvg_top"], fvg_bottom=sig["fvg_bottom"],
                sweep_price=sig["sweep_price"], entry_bar_index=i,
            )

            if debug:
                logger.info(f"  [{sym}] Opened {side} @ ${entry_price:.2f} SL=${sl:.2f} TP=${tp:.2f} "
                            f"qty={qty:.4f} risk=${risk_amt:.2f} (sweep@{sig['sweep_idx']} fvg@{sig['fvg_idx']} gap={sig['gap_pct']:.2f}%)")

    # ── Results ───────────────────────────────────────────────────────
    total_trades = len(closed_trades)
    if total_trades == 0:
        elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
        logger.info(f"  [{symbol}] No trades ({elapsed:.0f}s)")
        return {"symbol": symbol, "month": str(before or "latest"),
                "data_range": data_range, "total_trades": 0, "total_profit": 0.0}

    wins = sum(1 for t in closed_trades if t.result == "WIN")
    losses = sum(1 for t in closed_trades if t.result == "LOSS")
    total_profit = sum(t.profit for t in closed_trades)
    gross_profits = sum(t.profit for t in closed_trades if t.result == "WIN")
    gross_losses = abs(sum(t.profit for t in closed_trades if t.result == "LOSS"))
    pf = gross_profits / gross_losses if gross_losses > 0 else (999 if gross_profits > 0 else 0)

    # Trade-by-trade max drawdown
    equity = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    max_dd = 0.0
    for t in sorted(closed_trades, key=lambda x: x.entry_time):
        equity += t.profit
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    win_rate = wins / total_trades
    avg_rr = sum(t.rr for t in closed_trades) / total_trades

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    logger.info(f"  ── {symbol} Results ──")
    logger.info(f"  Trades: {total_trades} (W:{wins} L:{losses}) | WR: {win_rate*100:.1f}% | PF: {pf:.2f}")
    logger.info(f"  P&L: ${total_profit:.2f} | DD: {max_dd*100:.1f}% | Avg RR: {avg_rr:.2f}")

    return {
        "symbol": symbol, "month": str(before or "latest"),
        "data_range": data_range,
        "total_trades": total_trades, "wins": wins, "losses": losses,
        "win_rate": win_rate, "total_profit": round(total_profit, 2),
        "profit_factor": round(pf, 2),
        "max_drawdown": round(max_dd, 4),
        "avg_rr": round(avg_rr, 2),
        "gross_profits": round(gross_profits, 2),
        "gross_losses": round(gross_losses, 2),
        "capital_remaining": round(balance, 2),
        "still_open": len(open_positions),
    }


# ── Main ────────────────────────────────────────────────────────────────

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Combo 521 Strategy — 5-Year Backtest")
    parser.add_argument("--months", type=int, default=60,
                        help="Number of months (default 60 = 5 years)")
    parser.add_argument("--offset", type=int, default=None,
                        help="Run a single month at this offset (0=newest)")
    parser.add_argument("--debug", action="store_true",
                        help="Per-trade logging")
    parser.add_argument("--fee-pct", type=float, default=FEE_PCT,
                        help=f"Round-trip fee %% (default {FEE_PCT})")
    parser.add_argument("--sl-multiplier", type=float, default=SL_MULTIPLIER,
                        help=f"ATR multiplier for SL (default {SL_MULTIPLIER})")
    parser.add_argument("--min-gap-pct", type=float, default=FVG_MIN_GAP_PCT,
                        help=f"Minimum FVG gap %% (default {FVG_MIN_GAP_PCT})")
    parser.add_argument("--capital", type=float, default=INITIAL_CAPITAL,
                        help=f"Starting capital (default ${INITIAL_CAPITAL:,.0f})")
    parser.add_argument("--sl-slippage-pct", type=float, default=0.05,
                        help="SL exit slippage %% (default 0.05)")
    parser.add_argument("--tp-slippage-pct", type=float, default=0.02,
                        help="TP exit slippage %% (default 0.02)")
    parser.add_argument("--no-next-candle-entry", action="store_true",
                        help="Disable next-candle-open deferral — use immediate FVG edge entry")
    parser.add_argument("--risk-pct", type=float, default=RISK_PER_TRADE_PCT,
                        help=f"Risk per trade %% of balance (default {RISK_PER_TRADE_PCT})")
    args = parser.parse_args()

    next_candle_entry = not args.no_next_candle_entry

    logger.remove()
    logger.add(sys.stderr, level="INFO" if not args.debug else "DEBUG",
               format="<level>{level: <8}</level> | {message}")

    today = datetime.now(timezone.utc).date()

    test_capital = args.capital

    if args.offset is not None:
        offsets = [max(0, args.offset)]
    else:
        num_months = max(args.months, 1)
        offsets = list(reversed(range(num_months)))

    print("\n" + "=" * 70)
    print(f"  📊 COMBO 521 STRATEGY BACKTEST")
    print(f"  {'='*70}")
    if args.offset is not None:
        end_date = today - timedelta(days=args.offset * 30)
        print(f"  Single month ending {end_date.strftime('%b %d, %Y')}")
    else:
        print(f"  Period: {args.months} months ({args.months/12:.1f} years)")
    print(f"\n  Strategy Parameters:")
    print(f"    premium_discount=True    swing_lookback={SWING_LOOKBACK}")
    print(f"    max_bars_after_sweep={MAX_BARS_AFTER_SWEEP}    fvg.min_gap_pct={args.min_gap_pct}%")
    print(f"    entry_mode={ENTRY_MODE}    fixed_r={FIXED_R}")
    print(f"    SL: {args.sl_multiplier}x ATR    Fee: {args.fee_pct}% round-trip")
    print(f"    Capital: ${test_capital:,.0f}    Risk: {args.risk_pct}%/trade")
    if next_candle_entry:
        print(f"    Entry: next-candle open")
    else:
        print(f"    Entry: immediate FVG edge")
    print(f"    Slippage: SL={args.sl_slippage_pct}% TP={args.tp_slippage_pct}%")
    print(f"  {'='*70}\n")

    all_results = []
    for month_idx, month_offset in enumerate(offsets):
        end_date = today - timedelta(days=month_offset * 30)
        before_str = end_date.isoformat()
        month_label = end_date.strftime("%Y-%m")

        if args.offset is None:
            print(f"\n{'━'*70}")
            print(f"  Month {month_idx + 1}/{len(offsets)} — ending {end_date.strftime('%b %d, %Y')}")
            print(f"{'━'*70}")

        r = await backtest_month(
            SYMBOL, before=before_str, debug=args.debug, fee_pct=args.fee_pct,
            sl_multiplier=args.sl_multiplier,
            sl_slippage_pct=args.sl_slippage_pct,
            tp_slippage_pct=args.tp_slippage_pct,
            next_candle_entry=next_candle_entry,
            risk_pct=args.risk_pct,
        )
        all_results.append(r)

        if r["total_trades"] > 0:
            print(f"  {SYMBOL}: {r['total_trades']} trades | "
                  f"W:{r['wins']} L:{r['losses']} | "
                  f"WR: {r['win_rate']*100:.1f}% | "
                  f"P&L: ${r['total_profit']:.2f} | "
                  f"DD: {r['max_drawdown']*100:.1f}%")
        else:
            print(f"  {SYMBOL}: No trades")

    # ── Combined Summary ──────────────────────────────────────────────
    total_months = len(all_results)
    total_trades = sum(r["total_trades"] for r in all_results)
    total_wins = sum(r["wins"] for r in all_results)
    total_losses = sum(r["losses"] for r in all_results)
    total_profit = sum(r["total_profit"] for r in all_results)

    # Proper PF from per-trade gross profits/losses across all months
    gross_p_total = sum(r.get("gross_profits", 0) for r in all_results)
    gross_l_total = sum(r.get("gross_losses", 0) for r in all_results)
    pf = gross_p_total / gross_l_total if gross_l_total > 0 else (999 if gross_p_total > 0 else 0)

    # Max drawdown: worst single-month drawdown as approximation
    # (intra-month drawdowns are captured in per-month max_drawdown)
    max_dd = max((r.get("max_drawdown", 0) or 0) for r in all_results)

    overall_wr = total_wins / total_trades if total_trades > 0 else 0
    avg_rr = sum(r["avg_rr"] * r["total_trades"] for r in all_results) / total_trades if total_trades > 0 else 0
    total_return_pct = (total_profit / test_capital) * 100

    # Sharpe (monthly returns)
    monthly_rets = [r["total_profit"] / test_capital for r in all_results]
    avg_mr = sum(monthly_rets) / len(monthly_rets) if monthly_rets else 0
    std_mr = math.sqrt(sum((r - avg_mr)**2 for r in monthly_rets) / len(monthly_rets)) if len(monthly_rets) > 1 else 1
    sharpe = (avg_mr / std_mr) * math.sqrt(12) if std_mr > 0 else 0
    avg_monthly_trades = total_trades / total_months if total_months > 0 else 0

    print(f"\n\n{'='*70}")
    print(f"  📊 COMBO 521 — {total_months}-MONTH RESULTS")
    print(f"  Symbol: {SYMBOL}")
    print(f"{'='*70}")
    print(f"\n  {'─'*55}")
    print(f"  OVERALL PERFORMANCE")
    print(f"  {'─'*55}")
    print(f"  Total Trades:    {total_trades}  (W:{total_wins} L:{total_losses})")
    print(f"  Win Rate:        {overall_wr*100:.1f}%")
    print(f"  Total P&L:       ${total_profit:,.2f}")
    print(f"  Total Return:    {total_return_pct:.1f}%")
    print(f"  Profit Factor:   {pf:.2f}")
    print(f"  Max Drawdown:    {max_dd*100:.1f}%")
    print(f"  Avg R:R:         {avg_rr:.2f}")
    print(f"  Sharpe Ratio:    {sharpe:.2f}")
    print(f"  Avg Monthly:     {avg_monthly_trades:.1f} trades")
    print(f"  Final Capital:   ${test_capital + total_profit:,.2f}")

    print(f"\n  {'─'*55}")
    print(f"  MONTHLY BREAKDOWN")
    print(f"  {'─'*55}")
    print(f"  {'Month':<10} {'Trades':<8} {'WR%':<8} {'P&L':<12} {'PF':<8} {'DD%':<8} {'RR':<8}")
    for r in all_results:
        if r["total_trades"] > 0:
            print(f"  {r['month'][:7]:<10} {r['total_trades']:<8} {r['win_rate']*100:<7.1f}% "
                  f"${r['total_profit']:<9.2f} {r['profit_factor']:<8.2f} {r['max_drawdown']*100:<7.1f}% {r['avg_rr']:<8.2f}")
        else:
            print(f"  {r['month'][:7]:<10} {'0':<8} {'N/A':<8} {'$0.00':<12} {'0.00':<8} {'0.0%':<8} {'0.00':<8}")

    # Reference comparison
    print(f"\n\n{'='*70}")
    print(f"  SL Multiplier: {args.sl_multiplier}x ATR")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    asyncio.run(main())
