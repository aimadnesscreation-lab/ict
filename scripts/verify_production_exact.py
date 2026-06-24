"""
EXACT production reproduction: rolling 288-bar window, recompute the full
ICT pipeline each step, call combo.detect ONLY on the last bar — identical
to what api/main.py does every 5m candle close.

Counts how often a signal would fire in production over the last N steps,
and breaks down WHY the most recent bars produced nothing.
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

WINDOW = int(sys.argv[1]) if len(sys.argv) > 1 else 288  # live system fetches 288 bars
STEPS = 1500          # how many rolling closes to simulate
URL = "https://fapi.binance.com/fapi/v1/klines"


def fetch(symbol="ETHUSDT", interval="5m", total=WINDOW + STEPS + 50):
    out, end = [], None
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


def build():
    return (MarketStructure(n=2), FVGDetector(), LiquidityDetector(atr_threshold=0.10),
            SessionDetector(), PremiumDiscountDetector(),
            Combo521Detector(swing_lookback=2, max_bars_after_sweep=20,
                             min_gap_pct=0.05, entry_mode="proximal"))


def run_pipeline(win, ms, fvg, liq, ses, pd_):
    d = win.clone()
    d = ms.detect_swings(d)
    d = fvg.detect_fvgs(d)
    d = liq.detect_all(d)
    d = ses.detect_sessions(d)
    d = pd_.compute_zones(d)
    return d


def main():
    full = fetch()
    print(f"Fetched {len(full)} bars: {full['timestamp'][0]} .. {full['timestamp'][-1]}")
    ms, fvg, liq, ses, pd_, combo = build()

    fires = 0
    fire_examples = []
    last_discount = []
    steps_done = 0
    start = len(full) - STEPS
    for end_idx in range(start, len(full)):
        win = full.slice(end_idx - WINDOW + 1, WINDOW)
        d = run_pipeline(win, ms, fvg, liq, ses, pd_)
        last = len(d) - 1
        sigs = combo.detect(d, current_idx=last, symbol="ETHUSDT")
        steps_done += 1
        # record discount state of the final (just-closed) bar
        crow = d.row(last, named=True)
        last_discount.append(bool(crow.get("in_discount")))
        if sigs:
            fires += len(sigs)
            if len(fire_examples) < 10:
                for s in sigs:
                    fire_examples.append((str(s["timestamp"]),
                                          "BUY" if s["signal_type"] == "BUY" else "SELL",
                                          round(s["price"], 2)))

    print(f"\n=== PRODUCTION-EXACT reproduction ({steps_done} rolling closes, window={WINDOW}) ===")
    print(f"  signals that WOULD fire: {fires}")
    print(f"  rate: {fires/steps_done*100:.2f}% of closes  ->  {fires/steps_done*118:.2f} expected in 118 closes")
    disc_true = sum(last_discount)
    print(f"  final-bar in_discount: True={disc_true}  False={steps_done-disc_true}")
    print("  fire examples:", fire_examples[:10])

    # Focus on the most recent ~130 closes; list exact fire timestamps so we
    # can check them against the live server window (06:18 .. 16:05 UTC).
    recent = list(range(len(full) - 130, len(full)))
    rf = 0
    fire_ts = []
    for end_idx in recent:
        win = full.slice(end_idx - WINDOW + 1, WINDOW)
        d = run_pipeline(win, ms, fvg, liq, ses, pd_)
        last = len(d) - 1
        sigs = combo.detect(d, current_idx=last, symbol="ETHUSDT")
        if sigs:
            rf += len(sigs)
            close_ts = str(full.row(end_idx, named=True)["timestamp"])
            for s in sigs:
                fire_ts.append((close_ts, "BUY" if s["signal_type"] == "BUY" else "SELL",
                                round(s["price"], 2)))
    print(f"\n=== last 130 closes — exact fire timestamps (close time, UTC) ===")
    print(f"  total fires: {rf}")
    for ft in fire_ts:
        print("   ", ft)
    print(f"  window covered: {full.row(len(full)-130, named=True)['timestamp']} .. {full.row(len(full)-1, named=True)['timestamp']}")


if __name__ == "__main__":
    main()
