"""
Binance Futures Trading Engine.

Connects to Binance USDⓈ-M Futures via CCXT.
Handles symbol conversion (BTCUSDT → BTC/USDT:USDT), amount precision,
leverage setting, market entry orders, and STOP_MARKET / TAKE_PROFIT_MARKET
for stop-loss and take-profit.

Futures supports BOTH LONG and SHORT positions.

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
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


TRACKED_SYMBOLS = ["BTCUSDT", "ETHUSDT"]

DEFAULT_LEVERAGE = 3  # Default leverage for futures positions


def normalize_symbol(symbol: str) -> str:
    """Convert raw symbol (e.g. BTCUSDT) to CCXT futures unified format.

    Futures format: BTCUSDT → BTC/USDT:USDT (linear perpetual contract).
    Handles any symbol length — strips the trailing 'USDT' suffix.
    """
    if symbol.endswith("USDT"):
        base = symbol[:-4]  # Remove 'USDT' suffix
    else:
        base = symbol  # fallback
    return f"{base}/USDT:USDT"


def denormalize_symbol(market_symbol: str) -> str:
    """Convert CCXT unified symbol back to raw format.

    Handles both spot (BTC/USDT) and futures (BTC/USDT:USDT) formats.
    """
    base = market_symbol.split("/")[0]
    return f"{base}USDT"


class LiveExecutor:
    """
    Live Execution Engine — Binance USDⓈ-M Futures Trading.

    Connects to Binance Futures (Testnet or Live) via CCXT.
    Uses market orders for entry with STOP_MARKET stop-loss and
    TAKE_PROFIT_MARKET take-profit orders.

    FUTURES: Supports both LONG and SHORT positions.
    - quantity is in base currency (e.g. BTC for BTC/USDT)
    - Leverage scales buying power (default 3×)
    - Positions managed via fetch_positions()
    - SL/TP placed as reduce-only stop/take-profit market orders
    """

    def __init__(self, mode: str = "demo"):
        self.mode = mode.lower()
        self._markets_loaded = False

        # Load Binance credentials
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.secret = os.getenv("BINANCE_SECRET")
        self.passphrase = None

        if not all([self.api_key, self.secret]):
            logger.warning("Execution: Missing BINANCE_API_KEY / BINANCE_SECRET in environment.")
            self.exchange = None
            return

        # Initialize CCXT Binance Futures instance — USDⓈ-M
        config = {
            'apiKey': self.api_key,
            'secret': self.secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
                'hedgeMode': False,  # One-way mode (simpler position management)
            }
        }

        self.exchange = ccxt.binanceusdm(config)

        # Enable Sandbox mode
        if self.mode == "demo":
            self.exchange.enable_demo_trading(True)
            logger.info("Execution: Binance Futures Testnet mode enabled via enable_demo_trading.")
        else:
            logger.info("Execution: Binance FUTURES LIVE mode (use with caution).")

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

    def _get_price_tick(self, symbol: str) -> float:
        """Get the price tick size for a symbol from loaded market data.

        Returns the minimum price increment (e.g. 0.01 for ETHUSDT).
        Falls back to 0.01 if markets not loaded.
        """
        if not self.exchange or not self._markets_loaded:
            return 0.01
        market_symbol = normalize_symbol(symbol)
        market = self.exchange.markets.get(market_symbol)
        if not market:
            return 0.01
        precision = market.get('precision', {})
        return precision.get('price', 0.01)

    def _round_price(self, symbol: str, price: float) -> float:
        """Round a price to the nearest valid tick size for the symbol.

        Binance rejects orders with prices that don't match the tick size
        (e.g. ETHUSDT tick = 0.01, so 1845.234 becomes 1845.23).
        """
        tick = self._get_price_tick(symbol)
        if tick <= 0:
            return round(price, 2)
        return round(price / tick) * tick

    def _round_amount(self, symbol: str, amount: float) -> Optional[float]:
        """Round amount to the symbol's precision and validate it's within limits.
        Returns None if the amount is below the minimum.
        """
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
        """Fetch the wallet balance for a specific asset on the futures account.

        Uses the 'free' (available to open new positions) balance.
        """
        if not self.exchange:
            return 0.0
        try:
            balance = await self.exchange.fetch_balance()
            free = float(balance.get(asset, {}).get('free', 0.0))
            logger.debug(f"Execution: Futures {asset} balance = {free}")
            return free
        except Exception as e:
            logger.error(f"Execution: Failed to fetch balance: {e}")
            return 0.0

    async def get_total_balance(self, asset: str = "USDT") -> float:
        """Fetch the total (free + used) balance for a specific asset on futures."""
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
        """Return all open positions from the futures exchange.

        FUTURES: Uses fetch_positions() which returns real position data
        including entry price, unrealized PnL, and size per side.
        """
        if not self.exchange:
            return []
        try:
            positions = await self.exchange.fetch_positions()
            open_positions = []
            for p in positions:
                contracts = float(p.get('contracts', 0) or 0)
                if contracts > 0:
                    side = 'long' if p.get('side') == 'long' else 'short'
                    open_positions.append({
                        'symbol': p.get('symbol', ''),
                        'contracts': contracts,
                        'size': contracts,
                        'side': side,
                        'entryPrice': float(p.get('entryPrice', 0) or 0),
                        'unrealizedPnl': float(p.get('unrealizedPnl', 0) or 0),
                        'leverage': float(p.get('leverage', 1) or 1),
                        'liquidationPrice': float(p.get('liquidationPrice', 0) or 0),
                        'margin': float(p.get('initialMargin', 0) or 0),
                        'percentage': float(p.get('percentage', 0) or 0),
                    })
            return open_positions
        except Exception as e:
            logger.error(f"Execution: Failed to fetch futures positions: {e}")
            return []

    async def has_position(self, symbol: str) -> bool:
        """Check if there is an open futures position for a given symbol.

        Args:
            symbol: Raw symbol like 'BTCUSDT'
        Returns:
            True if we hold a meaningful position on the futures market
        """
        if not self.exchange:
            return False
        try:
            positions = await self.exchange.fetch_positions()
            market_symbol = normalize_symbol(symbol)
            for p in positions:
                if p.get('symbol') == market_symbol:
                    contracts = float(p.get('contracts', 0) or 0)
                    if contracts > 0:
                        return True
            return False
        except Exception as e:
            logger.error(f"Execution: has_position failed for {symbol}: {e}")
            return False

    async def get_position_for_symbol(self, symbol: str) -> Optional[Dict]:
        """Get the open futures position for a specific symbol, or None if not found."""
        positions = await self.get_open_positions()
        market_symbol = normalize_symbol(symbol)
        for p in positions:
            if p.get('symbol') == market_symbol:
                return p
        return None

    # ── Leverage ─────────────────────────────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int = DEFAULT_LEVERAGE):
        """Set leverage for a futures symbol.

        Args:
            symbol: Raw symbol like 'BTCUSDT'
            leverage: Leverage value (1-125 for most symbols)
        """
        if not self.exchange:
            return
        try:
            market_symbol = normalize_symbol(symbol)
            await self.exchange.set_leverage(leverage, market_symbol)
            logger.info(f"Execution: Leverage set to {leverage}x for {symbol}")
        except Exception as e:
            logger.debug(f"Execution: Leverage set skipped for {market_symbol}: {e}")

    # ── Order Placement ──────────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        sl: float,
        tp: float,
        use_limit_order: bool = False,
    ) -> Optional[Dict]:
        """
        Place Futures order with STOP_MARKET + TAKE_PROFIT_MARKET.

        Supports two entry modes:
          - Market (default): type='market', taker fee (0.04%)
          - Post-only limit: type='limit' with postOnly, maker fee (0.02%)
            The limit price is set slightly off-market to ensure maker status.
            If the order would be a taker, Binance rejects it (no fill).

        FUTURES: Supports both LONG and SHORT positions.

        Order flow:
          1. Set leverage for the symbol
          2. Place entry order (market or limit post-only)
          3. Place a STOP_MARKET order (reduce-only) for stop-loss
          4. Place a TAKE_PROFIT_MARKET order (reduce-only) for take-profit

        Args:
            symbol: Raw symbol like 'BTCUSDT'
            side: 'LONG' or 'SHORT'
            qty: Desired quantity in base currency
            price: Current market price (for reference/logging)
            sl: Stop-loss price
            tp: Take-profit price
            use_limit_order: If True, use post-only limit order for entry
                             (lower fee, may not fill immediately)

        Returns:
            Entry order dict on success, None on failure.
        """
        if not self.exchange:
            return None

        # Ensure markets are loaded for precision/limits
        await self._ensure_markets()

        # Convert to CCXT unified futures symbol
        market_symbol = normalize_symbol(symbol)

        # Validate and round quantity
        amount = self._round_amount(symbol, qty)
        if amount is None or amount <= 0:
            logger.warning(f"Execution: Invalid quantity {qty} for {symbol} after rounding")
            return None

        # Determine CCXT side from our side
        # One-way mode: side='buy' opens LONG / closes SHORT
        #               side='sell' opens SHORT / closes LONG
        if side.upper() == "LONG":
            ccxt_side = 'buy'
            opposite_side = 'sell'
        elif side.upper() == "SHORT":
            ccxt_side = 'sell'
            opposite_side = 'buy'
        else:
            logger.warning(f"Execution: Unknown side {side}")
            return None

        try:
            # 1. Set leverage
            await self.set_leverage(symbol, DEFAULT_LEVERAGE)

            logger.info(
                f"Execution: Opening {side} {market_symbol} qty={amount} "
                f"SL={sl} TP={tp}"
            )

            # 2. Entry: market or post-only limit
            if use_limit_order:
                # Get price precision from loaded market data
                price_decimals = 2  # default fallback
                if self.exchange and self._markets_loaded:
                    market = self.exchange.markets.get(market_symbol, {})
                    prec = market.get('precision', {})
                    price_tick = prec.get('price', 0.01)
                    if price_tick > 0:
                        price_decimals = max(1, -int(__import__('math').log10(price_tick)))

                # Post-only limit order: price slightly off-market to be a maker
                # LONG (buy): set price just below market to add liquidity
                # SHORT (sell): set price just above market to add liquidity
                if ccxt_side == 'buy':
                    limit_price = round(price * 0.999, price_decimals)
                else:
                    limit_price = round(price * 1.001, price_decimals)
                entry = await self.exchange.create_order(
                    symbol=market_symbol,
                    type='limit',
                    side=ccxt_side,
                    amount=amount,
                    price=limit_price,
                    params={'postOnly': True}
                )
                logger.info(f"  Post-only limit entry: {ccxt_side} {amount} @ {limit_price}")
            else:
                entry = await self.exchange.create_order(
                    symbol=market_symbol,
                    type='market',
                    side=ccxt_side,
                    amount=amount,
                    params={}
                )

            filled = float(entry.get('filled', 0))
            if filled <= 0:
                if use_limit_order:
                    logger.warning(f"  Limit order not yet filled, skipping SL/TP until next cycle")
                    return None  # Don't count as a trade — orchestrator can retry
                else:
                    filled = amount

            avg_entry = float(entry.get('price', 0) or price)
            logger.info(
                f"  Entry filled: {filled} @ {avg_entry} (requested {amount})"
            )

            # Round SL/TP prices to exchange tick size — Binance rejects orders
            # with invalid price precision (e.g. 1820.345 when tick=0.01).
            # This was the root cause of missing SL/TP on live positions.
            rounded_sl = self._round_price(symbol, sl)
            rounded_tp = self._round_price(symbol, tp)

            # Brief delay to let the exchange register the position before
            # placing reduce-only orders (prevents "reduce-only order rejected"
            # errors when the market entry hasn't fully settled).
            await asyncio.sleep(1)

            # 3. STOP_MARKET — stop-loss (reduce-only)
            # One-way mode: side alone determines direction, no positionSide needed
            try:
                await self.exchange.create_order(
                    symbol=market_symbol,
                    type='STOP_MARKET',
                    side=opposite_side,
                    amount=filled,
                    params={
                        'stopPrice': rounded_sl,
                        'reduceOnly': True,
                        'workingType': 'MARK_PRICE',
                    }
                )
                logger.info(f"  SL order placed: STOP_MARKET {opposite_side} @ {rounded_sl}")
            except Exception as e:
                logger.warning(f"  SL order failed: {e}")

            # 4. TAKE_PROFIT_MARKET — take-profit (reduce-only)
            try:
                await self.exchange.create_order(
                    symbol=market_symbol,
                    type='TAKE_PROFIT_MARKET',
                    side=opposite_side,
                    amount=filled,
                    params={
                        'stopPrice': rounded_tp,
                        'reduceOnly': True,
                        'workingType': 'MARK_PRICE',
                    }
                )
                logger.info(f"  TP order placed: TAKE_PROFIT_MARKET {opposite_side} @ {rounded_tp}")
            except Exception as e:
                logger.warning(f"  TP order failed: {e}")

            logger.info(
                f"Execution: {side} {market_symbol} entry={avg_entry:.2f} "
                f"SL={rounded_sl:.2f} TP={rounded_tp:.2f} qty={filled}"
            )
            return entry

        except Exception as e:
            logger.error(f"Execution: Order failed for {market_symbol}: {e}")
            return None

    # ── Order Cancellation ───────────────────────────────────────────

    async def cancel_all_orders(self, symbol: Optional[str] = None):
        """Cancel all open orders on the exchange, optionally for a specific symbol.
        Useful for cleanup and testing.
        """
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
