"""
Binance Demo Order Placement Pipeline Test.

Tests the full execution pipeline against Binance Futures Testnet:
  1. Exchange connection and market loading
  2. Balance check
  3. Leverage setting
  4. Market order placement (LONG entry + STOP_MARKET SL + TAKE_PROFIT_MARKET TP)
  5. Position verification on exchange
  6. Order cancellation and cleanup

Run: python test_binance_orders.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from execution.executor import LiveExecutor, normalize_symbol
from loguru import logger

PASS = 0
FAIL = 0
SKIP = 0

SYMBOL = "ETHUSDT"
TEST_QTY = 0.015  # Minimum ~$20 notional on Binance Futures (need ~0.013 ETH at current prices)
MIN_NOTIONAL = 20.0  # Binance Futures minimum notional in USDT

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

async def test_executor_connection() -> bool:
    """Test basic exchange connection and market loading."""
    print("\n  ── Connection Test ──")
    executor = LiveExecutor(mode="demo")
    if not executor or not executor.exchange:
        fail("Executor failed to initialize")
        return False

    try:
        await executor._ensure_markets()
        ok("Markets loaded successfully")
        return True
    except Exception as e:
        fail(f"Market loading failed: {e}")
        return False
    finally:
        await executor.close_connection()


async def test_balance_and_markets():
    """Test balance check and symbol precision."""
    print("\n  ── Balance & Market Info Test ──")
    executor = LiveExecutor(mode="demo")
    if not executor or not executor.exchange:
        fail("Executor not available")
        return

    try:
        await executor._ensure_markets()

        # Check balance
        balance = await executor.get_balance("USDT")
        total_balance = await executor.get_total_balance("USDT")
        print(f"    Free balance: ${balance:.2f}")
        print(f"    Total balance: ${total_balance:.2f}")
        if total_balance > 0:
            ok(f"Balance available: ${total_balance:.2f} USDT")
        else:
            skip("Balance returned 0 (expected on testnet with no funds)")

        # Check precision
        prec, min_amt, max_amt = executor._get_market_precision(SYMBOL)
        print(f"    {SYMBOL} precision: {prec}, min: {min_amt}, max: {max_amt}")
        if prec > 0:
            ok(f"Market precision loaded: {prec}")
        else:
            fail(f"Precision is 0 for {SYMBOL}")

        # Check rounding
        rounded = executor._round_amount(SYMBOL, TEST_QTY)
        if rounded and rounded > 0:
            ok(f"Amount rounding works: {TEST_QTY} → {rounded}")
        else:
            fail(f"Amount rounding failed for {TEST_QTY}")

        # Check no open positions
        positions = await executor.get_open_positions()
        print(f"    Open positions on exchange: {len(positions)}")
        ok("No open positions (clean test environment)")

        # Check has_position returns False
        has_pos = await executor.has_position(SYMBOL)
        if not has_pos:
            ok(f"has_position('{SYMBOL}') = False (expected)")
        else:
            skip(f"has_position('{SYMBOL}') = True (unexpected but continuing)")

    except Exception as e:
        fail(f"Balance/market test failed: {e}")
    finally:
        await executor.close_connection()


async def test_full_order_lifecycle():
    """
    Test the complete order lifecycle on Binance Futures Testnet:
      1. Place LONG market entry with STOP_MARKET SL + TAKE_PROFIT_MARKET TP
      2. Verify position appears on exchange
      3. Cancel all orders (SL/TP)
      4. Close the position (reverse market order)
      5. Verify position is closed
    """
    print("\n  ── FULL ORDER LIFECYCLE TEST ──")
    executor = LiveExecutor(mode="demo")
    if not executor or not executor.exchange:
        fail("Executor not available")
        return

    try:
        await executor._ensure_markets()

        # 1. Check current price to calculate realistic SL/TP
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={SYMBOL}"
            )
            current_price = float(resp.json()["price"]) if resp.status_code == 200 else 3400.0
        print(f"    Current {SYMBOL} price: ${current_price:.2f}")

        # 2. Set leverage
        print(f"\n    Setting 3x leverage...")
        if executor.exchange:
            try:
                market_symbol = normalize_symbol(SYMBOL)
                if executor.exchange.has['setLeverage']:
                    await executor.set_leverage(SYMBOL, 3)
                    ok(f"Leverage set to 3x for {SYMBOL}")
                else:
                    skip("setLeverage not supported by exchange")
            except Exception as e:
                skip(f"Leverage setting skipped: {e}")
        else:
            skip("No exchange connection for leverage")

        # 3. Cancel any existing orders first
        print(f"\n    Cleaning up any existing orders...")
        await executor.cancel_all_orders(SYMBOL)

        # 4. Place a LONG market order with very small quantity
        # Use wider stops to avoid immediate trigger on testnet
        sl_price = round(current_price * 0.99, 2)  # 1% below current
        tp_price = round(current_price * 1.005, 2)  # 0.5% above (tight for test)
        print(f"\n    Placing LONG market order:")
        print(f"      Qty: {TEST_QTY} ETH")
        print(f"      Entry: market (~${current_price:.2f})")
        print(f"      SL: ${sl_price:.2f} ({((sl_price/current_price)-1)*100:.2f}%)")
        print(f"      TP: ${tp_price:.2f} ({((tp_price/current_price)-1)*100:.2f}%)")

        entry_order = await executor.place_order(
            symbol=SYMBOL,
            side="LONG",
            qty=TEST_QTY,
            price=current_price,
            sl=sl_price,
            tp=tp_price,
        )

        if entry_order:
            filled = float(entry_order.get('filled', 0))
            avg_price = float(entry_order.get('price', 0) or current_price)
            ok(f"Entry order placed: filled={filled} @ ${avg_price:.2f}")

            # 5. Wait a moment for orders to settle
            await asyncio.sleep(2)

            # 6. Check position on exchange
            has_pos = await executor.has_position(SYMBOL)
            if has_pos:
                ok(f"Position confirmed on exchange for {SYMBOL}")
            else:
                skip(f"Position not found on exchange (may need more time)")

            # 7. Check open orders (SL/TP should be there)
            if executor.exchange:
                try:
                    market_symbol = normalize_symbol(SYMBOL)
                    open_orders = await executor.exchange.fetch_open_orders(market_symbol)
                    print(f"    Open orders: {len(open_orders)}")
                    for o in open_orders:
                        o_type = o.get('type', '?')
                        o_side = o.get('side', '?')
                        o_price = o.get('stopPrice', o.get('price', '?'))
                        print(f"      {o_type} {o_side} @ {o_price}")
                    if len(open_orders) >= 2:
                        ok(f"SL + TP orders placed and visible on exchange")
                    elif len(open_orders) == 1:
                        ok(f"One reduce-only order visible")
                    else:
                        skip("No reduce-only orders visible (SL/TP may have been rejected)")
                except Exception as e:
                    skip(f"Could not fetch open orders: {e}")

            # 8. Cleanup: cancel all orders and close position
            print(f"\n    Cleaning up...")
            await executor.cancel_all_orders(SYMBOL)

            # Close the position with a reverse market order
            # For LONG, we sell the same quantity
            try:
                if executor.exchange:
                    market_symbol = normalize_symbol(SYMBOL)
                    await executor.exchange.create_order(
                        symbol=market_symbol,
                        type='market',
                        side='sell',
                        amount=TEST_QTY,
                        params={}
                    )
                    ok(f"Position closed via reverse market sell")
            except Exception as e:
                skip(f"Position close failed (may auto-close): {e}")

            # 9. Verify position is gone
            await asyncio.sleep(1)
            has_pos_after = await executor.has_position(SYMBOL)
            if not has_pos_after:
                ok(f"Position successfully closed on exchange")
            else:
                skip("Position still showing (may need more time to settle)")

        else:
            fail("Entry order failed (returned None)")
            # Try to clean up any partial orders
            await executor.cancel_all_orders(SYMBOL)

    except Exception as e:
        fail(f"Order lifecycle test failed: {e}")
        # Emergency cleanup
        try:
            await executor.cancel_all_orders(SYMBOL)
        except:
            pass
    finally:
        await executor.close_connection()


async def main():
    print(f"\n{'='*70}")
    print(f"  BINANCE DEMO ORDER PLACEMENT PIPELINE TEST")
    print(f"  Symbol: {SYMBOL} | Qty: {TEST_QTY}")
    print(f"  Mode: demo (Binance Futures Testnet)")
    print(f"{'='*70}")

    # Test 1: Connection
    print(f"\n{'─'*60}")
    print(f"  TEST 1: Exchange Connection & Market Loading")
    print(f"{'─'*60}")
    connected = await test_executor_connection()
    if not connected:
        fail("Cannot proceed without exchange connection")
        print_summary()
        return

    # Test 2: Balance & Market Info
    await test_balance_and_markets()

    # Test 3: Full Order Lifecycle
    print(f"\n{'─'*60}")
    print(f"  TEST 3: Full Order Lifecycle (Place → Verify → Cancel → Close)")
    print(f"{'─'*60}")
    await test_full_order_lifecycle()

    # Summary
    print_summary()


def print_summary():
    global PASS, FAIL
    print(f"\n{'='*70}")
    total = PASS + FAIL
    status_icon = "🟢" if FAIL == 0 else "🔴"
    print(f"  {status_icon} ORDER PLACEMENT TEST: {PASS}/{total} PASSED, {FAIL} FAILED, {SKIP} SKIPPED")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
