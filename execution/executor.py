"""
Live Execution Engine — Binance Demo Trading (USDT-M Futures).

Supports Binance Demo Trading Portal and Binance Testnet with fallback.
Handles symbol conversion (BTCUSDT → BTC/USDT:USDT), amount precision,
and exchange position tracking to prevent duplicate trades.

Usage:
    executor = LiveExecutor(mode="demo")
    balance = await executor.get_balance()
    positions = await executor.get_open_positions()
    order = await executor.place_order("BTCUSDT", "LONG", 0.001, 50000, 49500, 51000)
    await executor.close_connection()
"""

import os
import asyncio
import ccxt.pro as ccxt
from loguru import logger
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def normalize_symbol(symbol: str) -> str:
    """Convert raw symbol (e.g. BTCUSDT) to CCXT unified futures format.
    
    Handles any symbol length: BTCUSDT → BTC/USDT:USDT, ETHUSDT → ETH/USDT:USDT, etc.
    This is length-agnostic — strips the trailing 'USDT' suffix.
    """
    if symbol.endswith("USDT"):
        base = symbol[:-4]  # Remove 'USDT' suffix
    else:
        base = symbol  # fallback
    return f"{base}/USDT:USDT"


def denormalize_symbol(market_symbol: str) -> str:
    """Convert CCXT unified symbol back to raw format (e.g. BTC/USDT:USDT → BTCUSDT)."""
    base = market_symbol.split("/")[0]
    return f"{base}USDT"


class LiveExecutor:
    """
    Generic Live Execution Engine.
    Supports Binance (Demo Trading Portal + Testnet) and OKX.
    
    For Binance USDT-M Futures:
      - quantity is in base currency (e.g. BTC for BTC/USDT)
      - contractSize is 1.0 (1 contract = 1 unit of base currency)
      - amount precision: BTC=0.0001, ETH=0.001
    """

    def __init__(self, mode: str = "demo", leverage: int = 10):
        self.mode = mode.lower()
        self.exchange_name = os.getenv("EXCHANGE_NAME", "binance").lower()
        self._markets_loaded = False
        self.leverage = leverage

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

        # Enable Demo/Sandbox mode
        if self.mode == "demo":
            if self.exchange_name == "binance":
                # Binance Demo Trading Portal (CCXT 4.5.6+)
                self.exchange.options['warnOnFetchOpenOrdersWithoutSymbol'] = False
                if hasattr(self.exchange, 'enable_demo_trading'):
                    self.exchange.enable_demo_trading(True)
                    logger.info("Execution: Binance Demo Trading Portal enabled.")
                else:
                    # Fallback to legacy testnet
                    self.exchange.set_sandbox_mode(True)
                    logger.info("Execution: Binance Testnet mode enabled (fallback).")
            else:
                self.exchange.set_sandbox_mode(True)
                logger.info(f"Execution: Initialized in {self.exchange_name.upper()} DEMO mode.")
        else:
            logger.info(f"Execution: Initialized in {self.exchange_name.upper()} LIVE mode.")

    # ── Market Info ───────────────────────────────────────────────────

    async def _ensure_markets(self):
        """Load market info once for precision and contract details."""
        if not self.exchange or self._markets_loaded:
            return
        try:
            await self.exchange.load_markets()
            self._markets_loaded = True
        except Exception as e:
            logger.warning(f"Execution: Failed to load markets: {e}")

    async def _set_leverage(self, symbol: str):
        """
        Set leverage for a specific symbol on Binance futures.
        Must be called after _ensure_markets() so exchange is ready.
        Uses cross-margin mode by default.
        """
        if not self.exchange or not self._markets_loaded:
            return
        try:
            market_symbol = normalize_symbol(symbol)
            if self.exchange_name == "binance":
                await self.exchange.set_leverage(self.leverage, market_symbol)
                # Also set margin mode to cross
                try:
                    await self.exchange.set_margin_mode('cross', market_symbol)
                except Exception:
                    pass  # May already be cross, ignore
            else:
                await self.exchange.set_leverage(self.leverage, market_symbol)
            logger.info(f"Execution: Leverage set to {self.leverage}x ({'cross'}) for {market_symbol}")
        except Exception as e:
            logger.warning(f"Execution: Failed to set leverage for {symbol}: {e}")

    def _get_market_precision(self, symbol: str) -> Tuple[float, float, float]:
        """Get amount precision, min amount, and max amount for a symbol.
        
        Returns (amount_precision, min_amount, max_amount).
        Falls back to sensible defaults if markets not loaded.
        """
        if not self.exchange or not self._markets_loaded:
            return (0.0001, 0.0001, 1000.0)

        market_symbol = normalize_symbol(symbol)
        market = self.exchange.markets.get(market_symbol)
        if not market:
            return (0.0001, 0.0001, 1000.0)

        precision = market.get('precision', {})
        amount_prec = precision.get('amount', 0.0001)
        limits = market.get('limits', {})
        amt_limits = limits.get('amount', {})
        min_amt = amt_limits.get('min', 0.0001)
        max_amt = amt_limits.get('max', 1000.0)
        return (amount_prec, min_amt, max_amt)

    def _round_amount(self, symbol: str, amount: float) -> Optional[float]:
        """Round amount to the symbol's precision and validate it's within limits.
        Returns None if the amount is below the minimum."""
        prec, min_amt, max_amt = self._get_market_precision(symbol)
        # Round down to precision (floor to avoid exceeding position limits)
        rounded = int(amount / prec) * prec if prec > 0 else amount
        if rounded < min_amt:
            logger.info(f"Execution: Amount {rounded} below minimum {min_amt} for {symbol}")
            return None
        if rounded > max_amt:
            logger.info(f"Execution: Amount {rounded} exceeds maximum {max_amt} for {symbol}, capping")
            rounded = max_amt
        return rounded

    # ── Balance ───────────────────────────────────────────────────────

    async def get_balance(self, asset: str = "USDT") -> float:
        """Fetch the available (free) balance for a specific asset on the exchange."""
        if not self.exchange:
            return 0.0
        try:
            balance = await self.exchange.fetch_balance()
            free = float(balance.get(asset, {}).get('free', 0.0))
            logger.debug(f"Execution: {asset} balance = {free}")
            return free
        except Exception as e:
            logger.error(f"Execution: Failed to fetch balance: {e}")
            return 0.0

    async def get_total_balance(self, asset: str = "USDT") -> float:
        """Fetch the total (free + used) balance for a specific asset."""
        if not self.exchange:
            return 0.0
        try:
            balance = await self.exchange.fetch_balance()
            total = float(balance.get(asset, {}).get('total', 0.0))
            return total
        except Exception as e:
            logger.error(f"Execution: Failed to fetch total balance: {e}")
            return 0.0

    # ── Positions ────────────────────────────────────────────────────

    async def get_open_positions(self) -> List[Dict]:
        """Return all open positions from the exchange (non-zero contracts)."""
        if not self.exchange:
            return []
        try:
            positions = await self.exchange.fetch_positions()
            return [
                p for p in positions
                if float(p.get('contracts', 0) or p.get('size', 0)) != 0
            ]
        except Exception as e:
            logger.error(f"Execution: Failed to fetch positions: {e}")
            return []

    async def has_position(self, symbol: str) -> bool:
        """Check if the exchange has an open position for a given symbol.
        
        Args:
            symbol: Raw symbol like 'BTCUSDT'
        Returns:
            True if there's an open position with non-zero size
        """
        positions = await self.get_open_positions()
        market_symbol = normalize_symbol(symbol)
        for p in positions:
            if p.get('symbol') == market_symbol:
                return True
        return False

    async def get_position_for_symbol(self, symbol: str) -> Optional[Dict]:
        """Get the open position for a specific symbol, or None if not found."""
        positions = await self.get_open_positions()
        market_symbol = normalize_symbol(symbol)
        for p in positions:
            if p.get('symbol') == market_symbol:
                return p
        return None

    # ── Order Placement ──────────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        sl: float,
        tp: float,
    ) -> Optional[Dict]:
        """
        Place Market order with attached Stop Loss and Take Profit on Binance Futures.

        Args:
            symbol: Raw symbol like 'BTCUSDT'
            side: 'LONG' or 'SHORT'
            qty: Quantity in base currency (e.g. BTC for BTC/USDT)
            price: Current market price (for reference/logging)
            sl: Stop-loss price
            tp: Take-profit price

        Returns:
            Entry order dict on success, None on failure.
        """
        if not self.exchange:
            return None

        # Ensure markets are loaded for precision/limits
        await self._ensure_markets()

        # Set the configured leverage for this symbol before placing orders
        await self._set_leverage(symbol)

        # Convert to CCXT unified symbol
        market_symbol = normalize_symbol(symbol)

        # Validate and round quantity
        amount = self._round_amount(symbol, qty)
        if amount is None or amount <= 0:
            logger.warning(f"Execution: Invalid quantity {qty} for {symbol} after rounding")
            return None

        order_side = 'buy' if side.upper() == "LONG" else 'sell'
        sl_side = 'sell' if side.upper() == "LONG" else 'buy'

        try:
            logger.info(
                f"Execution: Opening {side} {market_symbol} qty={amount} "
                f"SL={sl} TP={tp}"
            )

            # 1. Entry Market Order
            entry = await self.exchange.create_order(
                symbol=market_symbol,
                type='market',
                side=order_side,
                amount=amount,
            )

            # 2. Stop Loss (stop_market for Binance, reduceOnly)
            await self.exchange.create_order(
                symbol=market_symbol,
                type='stop_market',
                side=sl_side,
                amount=amount,
                params={
                    'stopPrice': sl,
                    'reduceOnly': True,
                    'workingType': 'MARK_PRICE',
                },
            )

            # 3. Take Profit (take_profit_market for Binance, reduceOnly)
            await self.exchange.create_order(
                symbol=market_symbol,
                type='take_profit_market',
                side=sl_side,
                amount=amount,
                params={
                    'stopPrice': tp,
                    'reduceOnly': True,
                    'workingType': 'MARK_PRICE',
                },
            )

            logger.info(
                f"Execution: {side} {market_symbol} entry=${price:.2f} "
                f"SL=${sl:.2f} TP=${tp:.2f} qty={amount}"
            )
            return entry

        except Exception as e:
            logger.error(f"Execution: Order failed for {market_symbol}: {e}")
            return None

    # ── Order Cancellation ───────────────────────────────────────────

    async def cancel_all_orders(self, symbol: Optional[str] = None):
        """Cancel all open orders on the exchange, optionally for a specific symbol.
        Useful for cleanup and testing."""
        if not self.exchange:
            return
        try:
            if symbol:
                market_symbol = normalize_symbol(symbol)
                orders = await self.exchange.fetch_open_orders(market_symbol)
            else:
                orders = await self.exchange.fetch_open_orders()

            for order in orders:
                try:
                    await self.exchange.cancel_order(order['id'], order.get('symbol'))
                    logger.info(f"Execution: Cancelled order {order['id']} {order.get('symbol')}")
                except Exception as e:
                    logger.warning(f"Execution: Failed to cancel order {order['id']}: {e}")
        except Exception as e:
            logger.warning(f"Execution: Failed to fetch/cancel orders: {e}")

    # ── Connection ───────────────────────────────────────────────────

    async def close_connection(self):
        """Close the exchange connection cleanly."""
        if self.exchange:
            try:
                await self.exchange.close()
                logger.info("Execution: Connection closed.")
            except Exception as e:
                logger.warning(f"Execution: Error closing connection: {e}")
