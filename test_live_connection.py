"""
Binance Demo Trading Connection Test.

Tests:
  1. Exchange connection with provided credentials
  2. Balance fetch
  3. Market info loading
  4. Position query
  5. Place + cancel a small test order (to verify execution works)
  6. Connection cleanup
"""

import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from execution.executor import LiveExecutor, normalize_symbol
from dotenv import load_dotenv

load_dotenv()

PASS = 0
FAIL = 0


def ok(msg: str):
    global PASS
    PASS += 1
    print(f"  ✅ {msg}")


def fail(msg: str):
    global FAIL
    FAIL += 1
    print(f"  ❌ {msg}")


async def test_connection():
    global PASS, FAIL

    mode = os.getenv("EXCHANGE_MODE", "demo")
    exchange_name = os.getenv("EXCHANGE_NAME", "binance").lower()

    print(f"\n{'='*60}")
    print(f"  BINANCE DEMO TRADING — CONNECTION TEST")
    print(f"  Mode: {mode.upper()} | Exchange: {exchange_name.upper()}")
    print(f"{'='*60}\n")

    # ── 1. Create Executor ────────────────────────────────────────────

    print("  Step 1: Creating LiveExecutor...")
    executor = LiveExecutor(mode=mode)

    if not executor.exchange:
        fail("LiveExecutor has no exchange (missing credentials?)")
        print("\n  Make sure .env file contains:")
        print("    BINANCE_API_KEY=your_key")
        print("    BINANCE_SECRET=your_secret")
        print(f"  Or set EXCHANGE_NAME=okx and OKX_API_KEY/OKX_SECRET/OKX_PASSPHRASE\n")
        return
    ok(f"LiveExecutor created for {exchange_name.upper()}")

    try:
        # ── 2. Load Markets ──────────────────────────────────────────
        print("\n  Step 2: Loading market info...")
        await executor._ensure_markets()
        if executor._markets_loaded:
            ok("Market data loaded successfully")
        else:
            fail("Failed to load markets")

        # ── 3. Test Symbol Format ────────────────────────────────────
        print("\n  Step 3: Verifying symbol conversion...")
        test_cases = [
            ("BTCUSDT", "BTC/USDT:USDT"),
            ("ETHUSDT", "ETH/USDT:USDT"),
            ("DOGEUSDT", "DOGE/USDT:USDT"),
        ]
        for raw, expected in test_cases:
            result = normalize_symbol(raw)
            if result == expected:
                ok(f"  {raw} → {result}")
            else:
                fail(f"  {raw} → {result} (expected {expected})")

        # ── 4. Balance ───────────────────────────────────────────────
        print("\n  Step 4: Fetching account balance...")
        balance = await executor.get_balance("USDT")
        total_balance = await executor.get_total_balance("USDT")
        if balance >= 0:
            ok(f"USDT free balance: ${balance:,.2f}")
            ok(f"USDT total balance: ${total_balance:,.2f}")
        else:
            fail(f"Balance fetch returned {balance}")

        # ── 5. Open Positions ────────────────────────────────────────
        print("\n  Step 5: Checking open positions...")
        positions = await executor.get_open_positions()
        ok(f"Open positions on exchange: {len(positions)}")
        for p in positions:
            side = p.get("side", "?")
            size = float(p.get("contracts", 0) or p.get("size", 0))
            entry = float(p.get("entryPrice", 0))
            pnl = float(p.get("unrealizedPnl", 0))
            print(f"      {p.get('symbol', '?'):20s} | {side:4s} | {size:>8.4f} | "
                  f"Entry: ${entry:>8.2f} | PnL: ${pnl:>+8.2f}")

        # ── 6. has_position check ────────────────────────────────────
        print("\n  Step 6: Testing position check...")
        has_btc = await executor.has_position("BTCUSDT")
        has_eth = await executor.has_position("ETHUSDT")
        ok(f"has_position(BTCUSDT): {has_btc}")
        ok(f"has_position(ETHUSDT): {has_eth}")

        # ── 7. Test Order (small amount, cancel immediately) ─────────
        print("\n  Step 7: Placing and cancelling a test LIMIT order...")
        print("      (Using a small limit order to verify write access)")
        try:
            test_symbol = "ETHUSDT"
            market_symbol = normalize_symbol(test_symbol)
            market = executor.exchange.markets.get(market_symbol, {})
            limits = market.get('limits', {})
            
            # Use a SELL limit at a very high price (won't fill but satisfies notional)
            # Binance Futures requires min notional of 20 USDT for non-reduceOnly orders
            # At $100,000, a tiny 0.001 ETH gives notional = 100 USDT > 20
            test_side = 'sell'
            test_price = 100_000.0  # well above market (~$3500), won't fill
            test_qty = 0.001  # tiny amount
            
            # Round to market precision
            rounded_qty = executor._round_amount(test_symbol, test_qty)
            if rounded_qty is None:
                print(f"      Skipping — {test_qty} {test_symbol} below minimum amount")
            else:
                # Place a small LIMIT sell order far above market (won't fill)
                test_order = await executor.exchange.create_order(
                    symbol=market_symbol,
                    type='limit',
                    side=test_side,
                    amount=rounded_qty,
                    price=test_price,
                    params={'timeInForce': 'GTC'},
                )
                order_id = test_order.get('id', '?')
                ok(f"Test limit order placed: ID={order_id}, qty={rounded_qty}")

                # Verify it appears in open orders
                open_orders = await executor.exchange.fetch_open_orders(market_symbol)
                found = any(o.get('id') == order_id for o in open_orders)
                if found:
                    ok(f"Order confirmed in open orders")
                else:
                    fail("Order not found in open orders")

                # Cancel the test order
                await executor.exchange.cancel_order(order_id, market_symbol)
                ok(f"Test order cancelled successfully")

        except Exception as e:
            fail(f"Test order failed: {e}")
            print(f"      (Non-critical — demo account may restrict certain operations)")

        # ── 8. Cancel all orders (cleanup) ───────────────────────────
        print("\n  Step 8: Cleanup — cancelling any stray orders...")
        await executor.cancel_all_orders()
        ok("Stray orders cancelled")

    except Exception as e:
        fail(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # ── 9. Close connection ──────────────────────────────────────
        print("\n  Step 9: Closing connection...")
        await executor.close_connection()
        ok("Connection closed")

    # ── Summary ───────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    total = PASS + FAIL
    if FAIL == 0:
        print(f"  ✅ ALL {total} TESTS PASSED")
    else:
        print(f"  ⚠️  {PASS}/{total} PASSED, {FAIL} FAILED")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(test_connection())
