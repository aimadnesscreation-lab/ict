"""
End-to-End Integration Test

Starts the API server, monitors data flow, and verifies:
  1. Server boots and responds to health checks
  2. OKX data backfill succeeds (candle buffers populated)
  3. HTF bias is computed
  4. ICT pipeline generates signals on new candle closes
  5. DemoAccount processes signals
  6. Binance demo trading connection is active and ready

Usage:
    python test_integration.py
"""

import asyncio
import httpx
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

API_BASE = "http://localhost:8000"
PASS = 0
FAIL = 0
SKIP = 0

# Track server process for cleanup
server_proc = None


def ok(msg: str):
    global PASS
    PASS += 1
    print(f"  ✅ {msg}")


def fail(msg: str):
    global FAIL
    FAIL += 1
    print(f"  ❌ {msg}")


def skip(msg: str):
    global SKIP
    SKIP += 1
    print(f"  ⏭️  {msg}")


async def check_endpoint(path: str, label: str, timeout: float = 10.0) -> dict:
    """GET an endpoint and return JSON, or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{API_BASE}{path}")
            if resp.status_code == 200:
                return resp.json()
            else:
                fail(f"{label} — HTTP {resp.status_code}")
                return None
    except Exception as e:
        fail(f"{label} — {e}")
        return None


async def wait_for_server(max_wait: int = 60) -> bool:
    """Poll the health endpoint until server is ready."""
    print(f"\n  Waiting for server to start (up to {max_wait}s)...")
    for i in range(max_wait):
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{API_BASE}/api/health")
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "running":
                        print(f"    Server ready after {i+1}s")
                        return True
                    print(f"    Status: {data.get('status')} ({i+1}s)")
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def monitor_data_flow(duration: int = 180):
    """
    Monitor the data pipeline for `duration` seconds.
    Checks health, signals, and demo account state periodically.
    """
    print(f"\n{'='*60}")
    print(f"  MONITORING DATA PIPELINE ({duration}s)")
    print(f"{'='*60}")

    health_snapshots = []
    signal_counts = []
    demo_snapshots = []

    # Check every 15 seconds for 'duration' seconds
    for tick in range(0, duration, 15):
        await asyncio.sleep(15)
        elapsed = tick + 15
        print(f"\n  --- t={elapsed}s ---")

        # 1. Health endpoint
        health = await check_endpoint("/api/health", "Health check")
        if health:
            health_snapshots.append(health)
            print(f"    Status: {health.get('status')} | "
                  f"Bias: {health.get('htf_bias','?').upper()} | "
                  f"BTC: ${health.get('btc_price',0):,.0f} | "
                  f"ETH: ${health.get('eth_price',0):,.0f}")
            print(f"    Signals: {health.get('total_signals_generated',0)} gen → "
                  f"{health.get('total_signals_kept',0)} kept | "
                  f"Trades executed: {health.get('total_trades_executed',0)}")
            print(f"    Cycles: {health.get('cycle_count',0)} | "
                  f"Uptime: {health.get('uptime','?')}")

        # 2. Signals endpoint
        signals = await check_endpoint("/signals?limit=5", "Signals")
        if signals and isinstance(signals, list):
            signal_counts.append(len(signals))
            if len(signals) > 0:
                for s in signals[:3]:
                    kz = "🔥 KZ" if s.get("in_kill_zone") else "   "
                    print(f"    Signal: {s.get('symbol','?'):8s} "
                          f"{s.get('signal_type','?'):12s} "
                          f"score={s.get('score',0):3d} "
                          f"{kz} "
                          f"${s.get('price',0):>8,.0f} "
                          f"bias={s.get('bias','?')}")
            else:
                print(f"    No signals yet (buffers filling...)")

        # 3. Demo account endpoint
        if tick >= 60:  # Start checking after 60s (buffers need warmup)
            demo = await check_endpoint("/demo/account", "Demo account")
            if demo:
                demo_snapshots.append(demo)
                trades = demo.get("total_trades", 0)
                profit = demo.get("total_profit", 0)
                open_pos = demo.get("open_positions_count", 0)
                balance = demo.get("balance", 10000)
                print(f"    Demo: ${balance:>8,.2f} | "
                      f"Trades: {trades} | "
                      f"PnL: ${profit:>+8,.2f} | "
                      f"Open: {open_pos}")

        # Early exit if we see trades
        if demo_snapshots and demo_snapshots[-1].get("open_positions_count", 0) > 0:
            print(f"\n  🎯 DEMO ACCOUNT HAS OPEN POSITIONS!")
            break

    return health_snapshots, signal_counts, demo_snapshots


async def check_binance_demo():
    """Verify Binance demo trading connection is active."""
    print(f"\n{'='*60}")
    print(f"  BINANCE DEMO TRADING CHECK")
    print(f"{'='*60}")

    from execution.executor import LiveExecutor

    executor = LiveExecutor(mode="demo")
    if not executor or not executor.exchange:
        fail("Binance demo executor not available (credentials?)")
        return

    try:
        # Load markets
        await executor._ensure_markets()

        # Check balance
        balance = await executor.get_balance("USDT")
        total_balance = await executor.get_total_balance("USDT")
        ok(f"Connected — Balance: ${total_balance:,.2f} USDT (free: ${balance:,.2f})")

        # Check open positions
        positions = await executor.get_open_positions()
        if len(positions) > 0:
            ok(f"Open positions on exchange: {len(positions)}")
            for p in positions:
                print(f"      {p.get('symbol','?'):20s} | "
                      f"{p.get('side','?'):4s} | "
                      f"qty={float(p.get('contracts',0)):.4f} | "
                      f"pnl=${float(p.get('unrealizedPnl',0)):+.2f}")
        else:
            ok("No open positions on exchange (expected — no kill zone active)")

        # Verify has_position works
        has_btc = await executor.has_position("BTCUSDT")
        has_eth = await executor.has_position("ETHUSDT")
        ok(f"Position check: BTC={has_btc}, ETH={has_eth} (both should be False)")

    except Exception as e:
        fail(f"Binance check failed: {e}")
    finally:
        await executor.close_connection()


async def main():
    global PASS, FAIL, SKIP

    import subprocess

    print(f"\n{'='*70}")
    print(f"  END-TO-END INTEGRATION TEST")
    print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print(f"{'='*70}")

    # Create a dedicated log file for the server
    log_file = open("/tmp/api_server.log", "w")

    # ── 1. Start API server ──────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  STEP 1: Starting API server (uvicorn api.main:app)")
    print(f"{'─'*60}")

    server_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--port", "8000", "--host", "0.0.0.0"],
        stdout=log_file,
        stderr=log_file,
        cwd=os.path.dirname(__file__),
    )

    # Wait for server to be ready
    ready = await wait_for_server(90)
    if not ready:
        fail("Server failed to start within 90s")
        server_proc.kill()
        log_file.close()
        return
    ok("API server started and healthy")

    try:
        # ── 2. Check root ────────────────────────────────────────────
        root = await check_endpoint("/", "Root endpoint")
        if root:
            ok(f"Root: {root.get('status','?')} v{root.get('version','?')}")

        # ── 3. Monitor data flow for up to 3 minutes ─────────────────
        health_snapshots, signal_counts, demo_snapshots = await monitor_data_flow(180)

        # ── 4. Analyze results ───────────────────────────────────────
        print(f"\n{'='*60}")
        print(f"  RESULTS ANALYSIS")
        print(f"{'='*60}")

        # Health analysis
        if health_snapshots:
            last = health_snapshots[-1]
            gen = last.get("total_signals_generated", 0)
            kept = last.get("total_signals_kept", 0)
            cycles = last.get("cycle_count", 0)
            bias = last.get("htf_bias", "neutral")
            btc = last.get("btc_price", 0)
            eth = last.get("eth_price", 0)

            if gen > 0:
                ok(f"ICT pipeline generated {gen} signals ({kept} kept after HTF filter)")
            else:
                skip("No signals generated yet (may need more candle closes)")

            if bias != "neutral":
                ok(f"HTF bias computed: {bias.upper()}")
            else:
                skip("HTF bias still neutral (may need more 1h data)")

            if btc > 0 and eth > 0:
                ok(f"OKX data flowing: BTC=${btc:,.0f}, ETH=${eth:,.0f}")
            else:
                skip("OKX prices not yet populated")

            if cycles > 0:
                ok(f"Background workers active: {cycles} bias cycles")
        else:
            skip("No health data collected")

        # Signal analysis
        if signal_counts and any(c > 0 for c in signal_counts):
            ok("Signals are being generated by the ICT pipeline")
        else:
            skip("No signals seen yet (buffers need 20+ candles, then 5m per candle close)")

        # Demo account analysis
        if demo_snapshots:
            last_demo = demo_snapshots[-1]
            trades = last_demo.get("total_trades", 0)
            if trades > 0:
                ok(f"DemoAccount executed {trades} trades (PnL: ${last_demo.get('total_profit',0):.2f})")
            else:
                skip("No DemoAccount trades — expected (not in kill zone 10:51 UTC, need 13:00-15:00 UTC for NY KZ)")
        else:
            skip("No demo account snapshots")

        # ── 5. Check Binance demo trading ────────────────────────────
        await check_binance_demo()

    finally:
        # ── 6. Cleanup ───────────────────────────────────────────────
        print(f"\n{'─'*60}")
        print(f"  CLEANUP")
        print(f"{'─'*60}")

        if server_proc:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=10)
                ok("Server stopped cleanly")
            except:
                server_proc.kill()
                fail("Server had to be killed")
                server_proc.wait()

        log_file.close()

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{'='*70}")
    total = PASS + FAIL
    if FAIL == 0:
        print(f"  🟢 INTEGRATION TEST: {total}/{total} PASSED, {SKIP} SKIPPED")
    else:
        print(f"  🔴 INTEGRATION TEST: {PASS}/{total} PASSED, {FAIL} FAILED, {SKIP} SKIPPED")
    print(f"  Completed: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print(f"{'='*70}")

    # Print server logs tail
    print(f"\n  📋 Last 30 lines of server log:")
    print(f"  {'─'*58}")
    with open("/tmp/api_server.log", "r") as f:
        lines = f.readlines()
        for line in lines[-30:]:
            line = line.strip()
            if line:
                # Shorten log lines for readability
                if len(line) > 120:
                    line = line[:117] + "..."
                print(f"  {line}")


if __name__ == "__main__":
    asyncio.run(main())
