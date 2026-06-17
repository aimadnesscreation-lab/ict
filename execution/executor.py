import os
import asyncio
import ccxt.pro as ccxt
from loguru import logger
from typing import Dict, List, Optional
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class LiveExecutor:
    """
    Generic Live Execution Engine.
    Supports OKX and Binance (including Testnets).
    """
    def __init__(self, mode: str = "demo"):
        self.mode = mode.lower()
        self.exchange_name = os.getenv("EXCHANGE_NAME", "binance").lower()
        
        # Load credentials based on exchange
        if self.exchange_name == "binance":
            self.api_key = os.getenv("BINANCE_API_KEY")
            self.secret = os.getenv("BINANCE_SECRET")
            self.passphrase = None
        else:
            self.api_key = os.getenv("OKX_API_KEY")
            self.secret = os.getenv("OKX_SECRET")
            self.passphrase = os.getenv("OKX_PASSPHRASE")
        
        if not all([self.api_key, self.secret]) or (self.exchange_name == "okx" and not self.passphrase):
            logger.warning(f"Execution: Missing {self.exchange_name.upper()} credentials in environment.")
            self.exchange = None
            return

        # Initialize CCXT instance
        exchange_class = getattr(ccxt, self.exchange_name)
        config = {
            'apiKey': self.api_key,
            'secret': self.secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future' if self.exchange_name == "binance" else 'swap',
            }
        }
        if self.passphrase:
            config['password'] = self.passphrase
            
        self.exchange = exchange_class(config)
        
        # Enable Sandbox/Testnet mode
        if self.mode == "demo":
            if self.exchange_name == "binance":
                # For the NEW Binance Demo Trading portal
                self.exchange.options['brokerId'] = 'CCXT' # common practice
                # CCXT 4.5.6+ supports enable_demo_trading(True)
                if hasattr(self.exchange, 'enable_demo_trading'):
                    self.exchange.enable_demo_trading(True)
                else:
                    self.exchange.set_sandbox_mode(True)
                logger.info("Execution: Configured for BINANCE Unified Demo Trading.")
            else:
                self.exchange.set_sandbox_mode(True)
                logger.info(f"Execution: Initialized in {self.exchange_name.upper()} DEMO mode.")
        else:
            logger.info(f"Execution: Initialized in {self.exchange_name.upper()} LIVE mode.")

    async def get_balance(self, asset: str = "USDT") -> float:
        """Fetch the available balance for a specific asset."""
        if not self.exchange: return 0.0
        try:
            balance = await self.exchange.fetch_balance()
            # Binance uses 'free' or 'total', OKX uses standardized 'free'
            return float(balance.get(asset, {}).get('free', 0.0))
        except Exception as e:
            logger.error(f"Execution: Failed to fetch balance: {e}")
            return 0.0

    async def place_order(self, symbol: str, side: str, qty: float, 
                          price: float, sl: float, tp: float) -> Optional[Dict]:
        """
        Place Market order with attached Stop Loss and Take Profit.
        """
        if not self.exchange: return None

        # Standardize symbol (e.g. BTCUSDT -> BTC/USDT:USDT for CCXT Futures)
        market_symbol = f"{symbol[:3]}/{symbol[3:]}:USDT" if self.exchange_name == "binance" else f"{symbol[:3]}-{symbol[3:]}-SWAP"

        try:
            order_side = 'buy' if side.upper() == "LONG" else 'sell'
            sl_side = 'sell' if side.upper() == "LONG" else 'buy'
            
            logger.info(f"Execution: Opening {side} on {market_symbol}, qty: {qty}")
            
            # 1. Place Entry Market Order
            entry = await self.exchange.create_order(
                symbol=market_symbol, type='market', side=order_side, amount=qty
            )
            
            # 2. Place Stop Loss (standardized CCXT params for Binance/OKX)
            await self.exchange.create_order(
                symbol=market_symbol, type='stop_market' if self.exchange_name == "binance" else 'limit',
                side=sl_side, amount=qty,
                params={'stopPrice': sl, 'reduceOnly': True} if self.exchange_name == "binance" else {'stopLossPrice': sl, 'reduceOnly': True}
            )
            
            # 3. Place Take Profit
            await self.exchange.create_order(
                symbol=market_symbol, type='take_profit_market' if self.exchange_name == "binance" else 'limit',
                side=sl_side, amount=qty,
                params={'stopPrice': tp, 'reduceOnly': True} if self.exchange_name == "binance" else {'takeProfitPrice': tp, 'reduceOnly': True}
            )
            
            return entry
        except Exception as e:
            logger.error(f"Execution: Order failed: {e}")
            return None

    async def get_open_positions(self) -> List[Dict]:
        if not self.exchange: return []
        try:
            positions = await self.exchange.fetch_positions()
            return [p for p in positions if float(p.get('contracts', 0) or p.get('size', 0)) != 0]
        except Exception as e:
            logger.error(f"Execution: Failed to fetch positions: {e}")
            return []

    async def close_connection(self):
        if self.exchange: await self.exchange.close()
