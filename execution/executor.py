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


# Symbols tracked by the executor (matches api/main.py TRACKED_SYMBOLS)
TRACKED_SYMBOLS = ["BTCUSDT", "ETHUSDT"]


def normalize_symbol(symbol: str) -> str:
    """Convert raw symbol (e.g. BTCUSDT) to CCXT spot unified format.

    Spot format: BTCUSDT → BTC/USDT (no :USDT suffix, unlike futures).
    Handles any symbol length — strips the trailing 'USDT' suffix.
    """
    if symbol.endswith("USDT"):
        base = symbol[:-4]  # Remove 'USDT' suffix
    else:
        base = symbol  # fallback
    return f"{base}/USDT"


def denormalize_symbol(market_symbol: str) -> str:
    """Convert CCXT unified symbol back to raw format (e.g. BTC/USDT or BTC/USDT:USDT → BTCUSDT)."""
    base = market_symbol.split("/")[0]
    return f"{base}USDT"


class LiveExecutor:
    """
    Live Execution Engine — Spot Trading.

    Supports Binance Spot (Demo Trading Portal + Testnet) and OKX Spot.
    Uses market orders for entry, with attached stop-loss and take-profit orders.

    IMPORTANT: Spot trading only supports LONG positions. SHORT signals are
    skipped with a warning. For SHORT positions, margin or futures would be
    needed (not currently implemented).

    For Binance Spot:
      - quantity is in base currency (e.g. BTC for BTC/USDT)
      - No leverage (spot trades 1:1)
      - amount precision: BTC=0.00001, ETH=0.001
    """

    def __init__(self, mode: str = "demo", leverage: int = 1):
        self.mode = mode.lower()
        self.exchange_name = os.getenv("EXCHANGE_NAME", "binance").lower()
        self._markets_loaded = False
        self.leverage = leverage  # ignored for spot, kept for interface compatibility

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

        # Initialize CCXT instance — always spot mode
        exchange_class = getattr(ccxt, self.exchange_name)
        config = {
            'apiKey': self.api_key,
            'secret': self.secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
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
                    logger.info("Execution: Binance Demo Trading Portal enabled (Spot).")
                else:
                    # Fallback to legacy testnet
                    self.exchange.set_sandbox_mode(True)
                    logger.info("Execution: Binance Testnet mode enabled (Spot, fallback).")
            else:
                self.exchange.set_sandbox_mode(True)
                logger.info(f"Execution: Initialized in {self.exchange_name.upper()} SPOT DEMO mode.")
        else:
            logger.info(f"Execution: Initialized in {self.exchange_name.upper()} SPOT LIVE mode.")

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
        No-op for spot trading — spot has no leverage.
        Kept for interface compatibility.
        """
        pass

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
        """Return all open positions from the exchange.

        SPOT: Checks balance of base assets for tracked symbols.
        A "position" is simply a non-zero free balance of the base asset.
        """
        if not self.exchange:
            return []
        try:
            balance = await self.exchange.fetch_balance()
            positions = []
            for raw_symbol in TRACKED_SYMBOLS:
                base = raw_symbol.replace('USDT', '')
                free = float(balance.get(base, {}).get('free', 0))
                total = float(balance.get(base, {}).get('total', 0))
                if total > 0:
                    positions.append({
                        'symbol': normalize_symbol(raw_symbol),
                        'contracts': total,
                        'size': total,
                        'side': 'long',
                        'entryPrice': 0.0,  # Spot doesn't track entry price via balance
                        'unrealizedPnl': 0.0,
                    })
            return positions
        except Exception as e:
            logger.error(f"Execution: Failed to fetch spot positions: {e}")
            return []

    async def has_position(self, symbol: str) -> bool:
        """Check if the exchange has an open position for a given symbol.

        SPOT: Checks if the free balance of the base asset is > 0.

        Args:
            symbol: Raw symbol like 'BTCUSDT'
        Returns:
            True if we hold a non-zero balance of the base asset
        """
        if not self.exchange:
            return False
        try:
            balance = await self.exchange.fetch_balance()
            base = symbol.replace('USDT', '')
            free = float(balance.get(base, {}).get('free', 0))
            return free > 0
        except Exception as e:
            logger.error(f"Execution: has_position failed for {symbol}: {e}")
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
        Place Spot Market order with attached Stop Loss and Take Profit.

        SPOT LIMITATION: Only LONG positions are supported on spot markets.
        SHORT signals are skipped with a warning.

        For LONG positions, we:
          1. Market buy the base asset
          2. Place a STOP_LOSS sell order (triggers market sell when stop price hit)
          3. Place a TAKE_PROFIT sell order (triggers market sell when TP price hit)

        Args:
            symbol: Raw symbol like 'BTCUSDT'
            side: 'LONG' or 'SHORT' (SHORT is skipped on spot)
            qty: Quantity in base currency (e.g. BTC for BTC/USDT)
            price: Current market price (for reference/logging)
            sl: Stop-loss price
            tp: Take-profit price

        Returns:
            Entry order dict on success, None on failure.
        """
        if not self.exchange:
            return None

        # Spot can only go LONG
        if side.upper() != "LONG":
            logger.info(f"Execution: Skipping {side} {symbol} — spot trading only supports LONG")
            return None

        # Ensure markets are loaded for precision/limits
        await self._ensure_markets()

        # Convert to CCXT unified spot symbol
        market_symbol = normalize_symbol(symbol)

        # Validate and round quantity
        amount = self._round_amount(symbol, qty)
        if amount is None or amount <= 0:
            logger.warning(f"Execution: Invalid quantity {qty} for {symbol} after rounding")
            return None

        try:
            logger.info(
                f"Execution: Opening LONG {market_symbol} qty={amount} "
                f"SL={sl} TP={tp}"
            )

            # 1. Entry Market Order (buy base asset with USDT)
            entry = await self.exchange.create_order(
                symbol=market_symbol,
                type='market',
                side='buy',
                amount=amount,
            )

            # 2. Stop Loss — triggers a market sell when price drops to SL
            # Binance spot STOP_LOSS becomes a market order when stopPrice is hit
            await self.exchange.create_order(
                symbol=market_symbol,
                type='stop_loss',
                side='sell',
                amount=amount,
                params={
                    'stopPrice': sl,
                },
            )

            # 3. Take Profit — triggers a market sell when price rises to TP
            # Binance spot TAKE_PROFIT becomes a market order when stopPrice is hit
            await self.exchange.create_order(
                symbol=market_symbol,
                type='take_profit',
                side='sell',
                amount=amount,
                params={
                    'stopPrice': tp,
                },
            )

            logger.info(
                f"Execution: LONG {market_symbol} entry=${price:.2f} "
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
