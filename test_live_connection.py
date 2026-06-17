import asyncio
import os
from execution.executor import LiveExecutor
from loguru import logger

async def test_connection():
    mode = os.getenv("EXCHANGE_MODE", "demo")
    executor = LiveExecutor(mode=mode)
    
    exchange_name = executor.exchange_name.upper() if hasattr(executor, 'exchange_name') else "UNKNOWN"
    print(f"\n--- {exchange_name} {mode.upper()} Connection Test ---")
    
    if not executor.exchange:
        print(f"FAIL: {exchange_name} API credentials not found in .env")
        return

    try:
        balance = await executor.get_balance()
        print(f"SUCCESS: Connected to {exchange_name} {mode.upper()}")
        print(f"Available Balance: {balance} USDT")
        
        positions = await executor.get_open_positions()
        print(f"Open Positions: {len(positions)}")
        
    except Exception as e:
        print(f"FAIL: Connection error: {e}")
    finally:
        await executor.close_connection()

if __name__ == "__main__":
    asyncio.run(test_connection())
