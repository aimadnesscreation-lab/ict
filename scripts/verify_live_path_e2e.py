"""
End-to-end proof of the LIVE code path: build a 288-bar buffer ending at a
known fire bar and call TradingOrchestrator.process_candle_close exactly like
api.main._on_candle_close does. Confirms the orchestrator (not just the
detector) emits a signal and feeds DemoAccount.
"""
import sys, asyncio, urllib.request, json
from datetime import datetime, timezone
import polars as pl

sys.path.insert(0, ".")
from demo_account import DemoAccount
from trading_engine.orchestrator import TradingOrchestrator

URL = "https://fapi.binance.com/fapi/v1/klines"


def fetch(total=400):
    out, end = [], None
    while len(out) < total:
        u = f"{URL}?symbol=ETHUSDT&interval=5m&limit={min(1000,total-len(out))}"
        if end:
            u += f"&endTime={end}"
        ks = json.loads(urllib.request.urlopen(
            urllib.request.Request(u, headers={"User-Agent": "diag"}), timeout=20).read())
        if not ks:
            break
        out = ks + out
        end = ks[0][0] - 1
    return [{
        "timestamp": datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc).replace(tzinfo=None),
        "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
        "close": float(k[4]), "volume": float(k[5]),
    } for k in out]


async def main():
    rows = fetch(400)
    # find the 16:35 fire bar index
    target = datetime(2026, 6, 24, 16, 35)
    idx = next((i for i, r in enumerate(rows) if r["timestamp"] == target), None)
    if idx is None:
        print("target bar not in fetch window; using last bar")
        idx = len(rows) - 1
    # buffer the live system would hold at that close: 288 bars ending at idx,
    # plus one trailing (forming) bar that _on_candle_close slices off.
    lo = max(0, idx - 287)
    buf = rows[lo:idx + 2]  # include one extra trailing bar (the forming candle)
    df_full = pl.DataFrame(buf)
    df_5m = df_full.slice(0, len(df_full) - 1)  # EXACT live slice from _on_candle_close

    demo = DemoAccount(initial_balance=5000.0)
    orch = TradingOrchestrator(demo, live_executor=None, discord_bot=None, kill_zones_enabled=False)

    prices = {"ETHUSDT": float(rows[idx]["close"])}
    result = await orch.process_candle_close(
        symbol="ETHUSDT", df_5m=df_5m, df_15m=df_5m,
        current_prices=prices, htf_bias="neutral",
    )

    print(f"fire bar close time : {rows[idx]['timestamp']}")
    print(f"buffer bars passed  : {len(df_5m)}")
    print(f"signals_generated   : {result['signals_generated']}")
    print(f"orch.total_signals  : {orch.total_signals_generated}")
    for s in result["signals"]:
        print(f"  -> {s['signal_type']} @ trigger={s.get('trigger_price')} price={s['price']} discount={s['details']['discount']}")
    print(f"demo open positions : {len(demo.open_positions)} -> {list(demo.open_positions.keys())}")
    print("\nVERDICT:", "LIVE PATH EMITS SIGNAL ✅" if result["signals_generated"] > 0 else "NO SIGNAL ❌")


asyncio.run(main())
