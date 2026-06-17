"""
12-Month Backtest — Forced Binance Data Source

Patches OKX fetch to always fail, triggering the Binance fallback.
Runs all 12 months in parallel mode for speed.

Usage:
    python run_backtest_binance.py
    python run_backtest_binance.py --capital 10000
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

# ── Force Binance fallback by patching OKX to always fail ──
import backtest_okx

original_okx = backtest_okx._okx_fetch_history

async def failing_okx(*args, **kwargs):
    return None

backtest_okx._okx_fetch_history = failing_okx

print("=" * 70)
print("  📊 12-MONTH BACKTEST — BINANCE DATA SOURCE")
print("  OKX patched to always fail → fallback to Binance")
print("=" * 70)

# ── Run the backtest ──
# Override sys.argv so backtest_okx.main() picks up our args
if len(sys.argv) > 1 and "--capital" in sys.argv:
    idx = sys.argv.index("--capital")
    capital = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "10000"
    sys.argv = ["backtest_okx.py", "--months", "12", "--parallel", "--capital", capital]
else:
    sys.argv = ["backtest_okx.py", "--months", "12", "--parallel"]

asyncio.run(backtest_okx.main())
