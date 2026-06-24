"""
Diagnostic: does the LIVE detector fire at the expected rate?

Fetches a long window of ETHUSDT 5m from Binance Futures, runs the EXACT
live ICT pipeline + Combo521Detector used by the orchestrator, bar-by-bar,
and reports how many signals fire and which gate rejects setups.

This distinguishes "code is broken (0 over 30 days)" from
"market just hasn't given one (rate ~50/month)".
"""
import sys, time, urllib.request, json
from datetime import datetime, timezone
import polars as pl

sys.path.insert(0, ".")
from ict_engine.market_structure import MarketStructure
from ict_engine.fvg import FVGDetector
from ict_engine.liquidity import LiquidityDetector
from ict_engine.sessions import SessionDetector
from ict_engine.premium_discount import PremiumDiscountDetector
from signal_engine.combo521 import Combo521Detector

DAYS = 30
BARS = DAYS * 24 * 12  # 5m bars
URL = "https://fapi.binance.com/fapi/v1/klines"


def fetch(symbol="ETHUSDT", interval="5m", total=BARS):
    out = []
    end = None
    while len(out) < total:
        limit = min(1000, total - len(out))
        u = f"{URL}?symbol={symbol}&interval={interval}&limit={limit}"
        if end:
            u += f"&endTime={end}"
        req = urllib.request.Request(u, headers={"User-Agent": "diag"})
        ks = json.loads(urllib.request.urlopen(req, timeout=20).read())
        if not ks:
            break
        out = ks + out
        end = ks[0][0] - 1
        time.sleep(0.2)
    rows = [{
        "timestamp": datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc).replace(tzinfo=None),
        "open": float(k[1]), "high": float(k[2]),
        "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
    } for k in out]
    return pl.DataFrame(rows)


def main():
    print(f"Fetching ~{BARS} ETHUSDT 5m bars (~{DAYS} days)...")
    df = fetch()
    print(f"Got {len(df)} bars: {df['timestamp'][0]} .. {df['timestamp'][-1]}")
    ms = MarketStructure(n=2)
    fvg = FVGDetector()
    liq = LiquidityDetector(atr_threshold=0.10)
    ses = SessionDetector()
    pd_ = PremiumDiscountDetector()
    combo = Combo521Detector(swing_lookback=2, max_bars_after_sweep=20,
                             min_gap_pct=0.05, entry_mode="proximal")

    df = ms.detect_swings(df)
    df = fvg.detect_fvgs(df)
    df = liq.detect_all(df)
    df = ses.detect_sessions(df)
    df = pd_.compute_zones(df)

    # Column sanity
    needed = ["liquidity_sweep_type", "fvg_type", "fvg_top", "fvg_bottom", "in_discount", "atr"]
    print("\n=== column presence / non-null counts ===")
    for c in needed:
        if c in df.columns:
            nn = df[c].drop_nulls().len()
            print(f"  {c:24s} present  non-null={nn}")
        else:
            print(f"  {c:24s} MISSING  <-- pipeline bug")

    # Raw component counts over the whole window
    print("\n=== raw component frequency (whole window) ===")
    if "liquidity_sweep_type" in df.columns:
        sv = df["liquidity_sweep_type"].value_counts()
        print("  sweeps:", sv.to_dicts())
    if "fvg_type" in df.columns:
        fv = df["fvg_type"].value_counts()
        print("  fvgs:", fv.to_dicts())
    if "in_discount" in df.columns:
        print("  in_discount True count:", df.filter(pl.col("in_discount") == True).height)

    # Bar-by-bar detect (exact live call)
    total = 0
    by_side = {"LONG": 0, "SHORT": 0}
    first_few = []
    start = 25
    for idx in range(start, len(df)):
        sigs = combo.detect(df, current_idx=idx, symbol="ETHUSDT")
        if sigs:
            total += len(sigs)
            for s in sigs:
                by_side[s["bias"].upper() if s["bias"] != "bullish" else "LONG"] = by_side.get("LONG", 0)
            for s in sigs:
                side = "LONG" if s["signal_type"] == "BUY" else "SHORT"
                by_side[side] += 1
                if len(first_few) < 8:
                    ts = s["timestamp"]
                    first_few.append((str(ts), side, round(s["price"], 2)))

    print("\n=== LIVE DETECTOR firing rate ===")
    print(f"  bars evaluated: {len(df) - start}")
    print(f"  signals fired : {total}")
    print(f"  by side       : {by_side}")
    rate_month = total / DAYS * 30
    print(f"  implied rate  : {rate_month:.1f} signals / 30 days")
    exp_10h = total / (len(df) - start) * 118
    print(f"  expected in 118 bars (~9.8h): {exp_10h:.2f} signals")
    print("\n  first few signals:")
    for f in first_few:
        print("   ", f)


if __name__ == "__main__":
    main()
