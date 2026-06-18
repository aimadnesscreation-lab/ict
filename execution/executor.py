"""
Binance Spot Trading Engine.

Connects to Binance Spot (Demo Trading Portal or Testnet) via CCXT.
Handles symbol conversion (BTCUSDT → BTC/USDT), amount precision,
OCO order placement, and balance-based position tracking.

Usage:
    executor = LiveExecutor(mode="demo")
    balance = await executor.get_balance()
    positions = await executor.get_open_positions()
    order = await executor.place_order("BTCUSDT", "LONG", 0.001, 50000, 49500, 51000)
    await executor.close_connection()
"""

import os
import ccxt.pro as ccxt
from loguru import logger
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


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
    Live Execution Engine — Binance Spot Trading.

    Connects to Binance Spot (Demo Trading Portal or Testnet) via CCXT.
    Uses market orders for entry with OCO (One-Cancels-Other) stop-loss
    and take-profit orders.

    SPOT ONLY: Only supports LONG positions. SHORT signals are filtered
    upstream by the TradingOrchestrator.

    For Binance Spot:
      - quantity is in base currency (e.g. BTC for BTC/USDT)
      - No leverage (spot trades 1:1)
      - amount precision: BTC=0.00001, ETH=0.001
    """

    def __init__(self, mode: str = "demo"):
        self.mode = mode.lower()
        self.exchange_name = "binance"
        self._markets_loaded = False

        # Load Binance credentials
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.secret = os.getenv("BINANCE_SECRET")
        self.passphrase = None

        if not all([self.api_key, self.secret]):
            logger.warning("Execution: Missing BINANCE_API_KEY / BINANCE_SECRET in environment.")
            self.exchange = None
            return

        # Initialize CCXT Binance instance — spot mode
        config = {
            'apiKey': self.api_key,
            'secret': self.secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
            }
        }

        self.exchange = ccxt.binance(config)

        # Enable Demo/Sandbox mode
        if self.mode == "demo":
            self.exchange.options['warnOnFetchOpenOrdersWithoutSymbol'] = False
            if hasattr(self.exchange, 'enable_demo_trading'):
                self.exchange.enable_demo_trading(True)
                logger.info("Execution: Binance Demo Trading Portal enabled (Spot).")
            else:
                self.exchange.set_sandbox_mode(True)
                logger.info("Execution: Binance Testnet mode enabled (Spot, fallback).")
        else:
            logger.info("Execution: Binance SPOT LIVE mode (use with caution).")

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

        SPOT: Checks if the free balance of the base asset exceeds a
        minimum threshold (to ignore dust from testing or fees).

        Minimum thresholds:
          - BTC: ≥ 0.001 (≈ $65 at $65k BTC)
          - ETH: ≥ 0.01  (≈ $18 at $1.8k ETH)
          - Others: ≥ 1 unit

        Args:
            symbol: Raw symbol like 'BTCUSDT'
        Returns:
            True if we hold a meaningful balance of the base asset
        """
        if not self.exchange:
            return False
        try:
            balance = await self.exchange.fetch_balance()
            base = symbol.replace('USDT', '')
            free = float(balance.get(base, {}).get('free', 0))
            # Minimum thresholds to ignore dust
            thresholds = {"BTC": 0.001, "ETH": 0.01}
            min_balance = thresholds.get(base, 1.0)
            return free >= min_balance
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
        Place Spot Market order with OCO Stop Loss + Take Profit.

        SPOT LIMITATION: Only LONG positions are supported. SHORT signals
        are skipped with a warning (would require margin).

        On Binance spot, SL and TP cannot be placed as separate sell orders
        because each one locks the base asset. Instead we use an OCO
        (One-Cancels-Other) order which combines both into a single order
        sharing the same quantity lock:
          1. Market buy the base asset
          2. Place an OCO sell: LIMIT at TP level + STOP_LOSS_LIMIT at SL level

        Args:
            symbol: Raw symbol like 'BTCUSDT'
            side: 'LONG' or 'SHORT' (SHORT is skipped on spot)
            qty: Desired quantity in base currency (actual fill may differ due to fees)
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

        # ═══ SPOT SIZING: Cap quantity to available USDT balance ═══
        # DemoAccount calculates qty using futures-style risk sizing:
        #   qty = risk_amount / sl_distance
        # This gives a qty with full notional = qty × price, which can exceed
        # the USDT balance. On spot (1:1, no leverage), we must cap to what
        # the balance can actually afford.
        usdt_balance = await self.get_balance()
        max_qty_by_balance = usdt_balance / price if price > 0 else qty
        capped_qty = min(qty, max_qty_by_balance)
        if capped_qty < qty:
            logger.info(
                f"Execution: Spot sizing cap — qty {qty} exceeds USDT balance "
                f"(${usdt_balance:.2f} ÷ ${price:.2f} = {max_qty_by_balance:.6f}), "
                f"using {capped_qty:.6f}"
            )
        # Validate and round quantity
        amount = self._round_amount(symbol, capped_qty)
        if amount is None or amount <= 0:
            logger.warning(f"Execution: Invalid quantity {capped_qty} for {symbol} after rounding")
            return None

        try:
            logger.info(
                f"Execution: Opening LONG {market_symbol} qty={amount} "
                f"SL={sl} TP={tp}"
            )

            # 1. Market Entry — buy the base asset
            entry = await self.exchange.create_order(
                symbol=market_symbol,
                type='market',
                side='buy',
                amount=amount,
            )

            # Determine the actual filled quantity.
            # On Binance spot, the entry order's 'filled' is the gross filled
            # amount. After the taker fee (~0.1%) is deducted, the actual
            # receivable balance is slightly less. We fetch the post-fill
            # balance to get the exact amount available for the OCO sell.
            filled = float(entry.get('filled', 0))
            if filled <= 0:
                filled = amount

            # Fetch actual balance after the market buy to account for fees
            try:
                post_balance = await self.exchange.fetch_balance()
                base_cur = symbol.replace('USDT', '')
                actual_free = float(post_balance.get(base_cur, {}).get('free', 0))
                if actual_free > 0:
                    actual_qty_raw = actual_free
                else:
                    # Fallback: estimate net after 0.1% taker fee
                    actual_qty_raw = filled * 0.999
            except Exception:
                actual_qty_raw = filled * 0.999  # Fallback: estimate after fee

            actual_qty = self._round_amount(symbol, actual_qty_raw)
            if actual_qty is None or actual_qty <= 0:
                logger.warning(f"Execution: Post-fill balance {actual_qty_raw} too small for {symbol} OCO")
                return entry

            logger.info(f"  Filled {filled} {market_symbol}, post-fee balance={actual_qty:.6f} (requested {amount})")

            # 2. OCO — combines Stop Loss + Take Profit in one order
            # On Binance spot, CCXT's type='oco' is rejected by market validation.
            # Instead we call privatePostOrderOco directly — POST /api/v3/order/oco
            # This places:
            #   - LIMIT sell at TP (fills when price rises to take-profit level)
            #   - STOP_LOSS_LIMIT sell triggered when price drops to SL
            # Both legs share the same quantity lock (no double-lock issue).
            oco_params = {
                'symbol': symbol.upper(),          # ETHUSDT (Binance raw format)
                'side': 'SELL',
                'quantity': actual_qty,
                'price': tp,                       # LIMIT price = take profit
                'stopPrice': sl,                   # Stop trigger = stop loss
                'stopLimitPrice': sl,              # Stop limit price = same as trigger
                'stopLimitTimeInForce': 'GTC',
            }

            # Format numbers to exchange precision
            try:
                oco_params['quantity'] = self.exchange.amount_to_precision(market_symbol, actual_qty)
                oco_params['price'] = self.exchange.price_to_precision(market_symbol, tp)
                oco_params['stopPrice'] = self.exchange.price_to_precision(market_symbol, sl)
                oco_params['stopLimitPrice'] = self.exchange.price_to_precision(market_symbol, sl)
            except Exception:
                pass  # Use raw floats if precision formatting fails

            oco_result = await self.exchange.privatePostOrderOco(oco_params)

            logger.info(
                f"Execution: LONG {market_symbol} entry=${price:.2f} "
                f"SL=${sl:.2f} TP=${tp:.2f} qty={actual_qty} (OCO placed, orderListId={oco_result.get('orderListId', '?')})"
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
