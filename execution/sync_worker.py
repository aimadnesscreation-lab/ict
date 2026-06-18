"""
Exchange Position Sync Worker.

Periodically reconciles DemoAccount (in-memory simulator) with actual
exchange positions from Binance. Handles three desync scenarios:

  1. SL/TP hit on exchange → DemoAccount still thinks position is open
     → Close position in DemoAccount, record trade with actual exchange exit data

  2. Exchange position closed manually (dashboard) → DemoAccount still open
     → Same as #1 — close in DemoAccount

  3. Quantity/side mismatch → Log discrepancy for monitoring

The worker runs every 30 seconds in the background alongside the crypto data
and HTF bias workers. It can also be triggered manually via the /sync endpoint.

Usage:
    sync_result = await sync_positions(demo_account, live_executor, latest_prices)
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field
from loguru import logger

from demo_account import DemoAccount, ClosedTrade
from execution.executor import denormalize_symbol

# ── Sync cycle interval ──────────────────────────────────────────────
SYNC_INTERVAL_SECONDS = 30  # Check every 30 seconds

# ── Sync Results ─────────────────────────────────────────────────────

@dataclass
class SyncResult:
    """Result of a single sync cycle."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    exchange_positions_checked: int = 0
    demo_positions_checked: int = 0
    positions_closed_from_exchange_sl: int = 0
    positions_closed_from_exchange_tp: int = 0
    positions_closed_from_exchange_manual: int = 0
    positions_mirrored: int = 0
    discrepancies: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ── Sync Logic ────────────────────────────────────────────────────────

async def sync_positions(
    demo_account: DemoAccount,
    live_executor: LiveExecutor,
    latest_prices: Dict[str, float],
    current_time: Optional[datetime] = None,
) -> SyncResult:
    """
    Reconcile DemoAccount's open positions with actual positions on the exchange.

    Args:
        demo_account: The in-memory DemoAccount instance
        live_executor: The LiveExecutor connected to Binance
        latest_prices: Dict of {symbol: current_price} for unrealized P&L calculation
        current_time: Optional timestamp override

    Returns:
        SyncResult with details of what was reconciled
    """
    result = SyncResult()
    result.timestamp = current_time or datetime.now(timezone.utc)

    if not live_executor or not live_executor.exchange:
        result.errors.append("No exchange connection available")
        return result

    now = current_time or datetime.now(timezone.utc)

    try:
        # Step 1: Fetch exchange positions
        exchange_positions = await live_executor.get_open_positions()
        result.exchange_positions_checked = len(exchange_positions)

        # Build lookup: raw symbol -> exchange position
        exchange_by_symbol: Dict[str, Dict] = {}
        for ep in exchange_positions:
            raw_sym = denormalize_symbol(ep.get("symbol", ""))
            exchange_by_symbol[raw_sym] = ep

        # Step 2: Check each DemoAccount position against exchange
        demo_positions_to_close: List[str] = []  # symbols to close in DemoAccount
        demo_to_close_info: Dict[str, Dict] = {}  # exit info per symbol

        for symbol, pos in list(demo_account.open_positions.items()):
            result.demo_positions_checked += 1

            if symbol in exchange_by_symbol:
                # Position exists on exchange — verify and reconcile
                ep = exchange_by_symbol[symbol]
                exchange_side = "LONG" if float(ep.get("contracts", 0) or 0) > 0 else "SHORT"
                exchange_qty = abs(float(ep.get("contracts", 0) or ep.get("size", 0)))

                # Check for side mismatch (shouldn't happen but log it)
                if exchange_side != pos.side:
                    result.discrepancies.append(
                        f"{symbol}: Demo side={pos.side}, Exchange side={exchange_side}"
                    )

                # Partial fill reconciliation
                # If exchange qty is significantly less than DemoAccount qty (>5% difference),
                # it means a partial exit happened on the exchange (manual close or liquidation).
                # Close the difference in DemoAccount as a partial fill trade.
                if exchange_qty > 0 and pos.quantity > 0:
                    qty_diff_pct = (pos.quantity - exchange_qty) / pos.quantity
                    
                    if qty_diff_pct > 0.05:  # >5% of position was partially closed
                        # Calculate what was closed: qty_diff = closed portion
                        closed_qty = pos.quantity - exchange_qty
                        current_price = latest_prices.get(symbol, 0)
                        
                        # Guess exit reason from price position relative to SL/TP
                        if pos.side == "LONG":
                            if current_price <= pos.stop_loss:
                                exit_reason = "STOP_LOSS"
                                exit_price = pos.stop_loss
                            elif current_price >= pos.take_profit:
                                exit_reason = "TAKE_PROFIT"
                                exit_price = pos.take_profit
                            else:
                                exit_reason = "MANUAL"
                                exit_price = current_price
                        else:
                            if current_price >= pos.stop_loss:
                                exit_reason = "STOP_LOSS"
                                exit_price = pos.stop_loss
                            elif current_price <= pos.take_profit:
                                exit_reason = "TAKE_PROFIT"
                                exit_price = pos.take_profit
                            else:
                                exit_reason = "MANUAL"
                                exit_price = current_price
                        
                        # Calculate PnL for the closed portion
                        if pos.side == "LONG":
                            partial_profit = (exit_price - pos.entry_price) * closed_qty
                        else:
                            partial_profit = (pos.entry_price - exit_price) * closed_qty
                        
                        partial_rr = abs(exit_price - pos.entry_price) / abs(pos.entry_price - pos.stop_loss) if abs(pos.entry_price - pos.stop_loss) > 0 else 0
                        partial_result = "WIN" if partial_profit > 0 else ("LOSS" if partial_profit < 0 else "BREAK_EVEN")
                        
                        # Update DemoAccount balance with partial profit
                        demo_account.balance += partial_profit
                        demo_account._daily_pnl += partial_profit
                        if demo_account.balance > demo_account._peak_balance:
                            demo_account._peak_balance = demo_account.balance
                        
                        # Update position quantity to match exchange
                        pos.quantity = exchange_qty
                        pos.risk_amount = pos.risk_amount * (exchange_qty / (exchange_qty + closed_qty))
                        
                        # Record partial fill trade
                        partial_trade = ClosedTrade(
                            symbol=pos.symbol,
                            signal_type=pos.signal_type,
                            side=pos.side,
                            entry_time=pos.entry_time,
                            exit_time=now,
                            entry_price=pos.entry_price,
                            exit_price=exit_price,
                            stop_loss=pos.stop_loss,
                            take_profit=pos.take_profit,
                            quantity=closed_qty,
                            profit=partial_profit,
                            profit_pct=partial_profit / (pos.entry_price * closed_qty) if pos.entry_price > 0 and closed_qty > 0 else 0,
                            rr=round(partial_rr, 2),
                            result=partial_result,
                            exit_reason=f"PARTIAL_{exit_reason}",
                        )
                        demo_account.closed_trades.append(partial_trade)
                        
                        logger.info(
                            f"[Sync] Partial fill {pos.side} {symbol}: {closed_qty:.4f}/{closed_qty+exchange_qty:.4f} units "
                            f"closed ({exit_reason}) profit=${partial_profit:.2f}"
                        )
                        result.positions_closed_from_exchange_manual += 1
                    elif abs(exchange_qty - pos.quantity) / max(exchange_qty, pos.quantity) > 0.01:
                        # Small quantity mismatch (>1%) — log as discrepancy but don't reconcile
                        result.discrepancies.append(
                            f"{symbol}: Demo qty={pos.quantity:.4f}, Exchange qty={exchange_qty:.4f} "
                            f"(diff={qty_diff_pct*100:.1f}%)"
                        )
            else:
                # Position NOT on exchange — it was closed (SL/TP hit or manual)
                # Determine the most likely exit reason and price
                current_price = latest_prices.get(symbol, 0)

                if pos.side == "LONG":
                    # Could have hit SL or TP
                    if current_price <= pos.stop_loss or current_price < pos.entry_price:
                        exit_reason = "STOP_LOSS"
                        exit_price = pos.stop_loss
                    elif current_price >= pos.take_profit:
                        exit_reason = "TAKE_PROFIT"
                        exit_price = pos.take_profit
                    else:
                        exit_reason = "MANUAL"
                        exit_price = current_price
                else:  # SHORT
                    if current_price >= pos.stop_loss or current_price > pos.entry_price:
                        exit_reason = "STOP_LOSS"
                        exit_price = pos.stop_loss
                    elif current_price <= pos.take_profit:
                        exit_reason = "TAKE_PROFIT"
                        exit_price = pos.take_profit
                    else:
                        exit_reason = "MANUAL"
                        exit_price = current_price

                demo_positions_to_close.append(symbol)
                demo_to_close_info[symbol] = {
                    "exit_reason": exit_reason,
                    "exit_price": exit_price,
                    "current_price": current_price,
                }

                if exit_reason == "STOP_LOSS":
                    result.positions_closed_from_exchange_sl += 1
                elif exit_reason == "TAKE_PROFIT":
                    result.positions_closed_from_exchange_tp += 1
                else:
                    result.positions_closed_from_exchange_manual += 1

        # Step 3: Close detected positions in DemoAccount
        for symbol in demo_positions_to_close:
            pos = demo_account.open_positions.get(symbol)
            if pos is None:
                continue

            info = demo_to_close_info[symbol]
            exit_price = info["exit_price"]
            exit_reason = info["exit_reason"]

            # Calculate PnL
            if pos.side == "LONG":
                profit = (exit_price - pos.entry_price) * pos.quantity
            else:
                profit = (pos.entry_price - exit_price) * pos.quantity

            rr = abs(exit_price - pos.entry_price) / abs(pos.entry_price - pos.stop_loss) \
                if abs(pos.entry_price - pos.stop_loss) > 0 else 0
            result_type = "WIN" if profit > 0 else ("LOSS" if profit < 0 else "BREAK_EVEN")

            # Update DemoAccount balance
            demo_account.balance += profit
            demo_account._daily_pnl += profit
            if demo_account.balance > demo_account._peak_balance:
                demo_account._peak_balance = demo_account.balance

            # Track SL for cooldown
            if exit_reason == "STOP_LOSS":
                demo_account._last_sl[symbol] = {"time": now, "side": pos.side}

            # Create and record closed trade
            trade = ClosedTrade(
                symbol=pos.symbol,
                signal_type=pos.signal_type,
                side=pos.side,
                entry_time=pos.entry_time,
                exit_time=now,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                stop_loss=pos.stop_loss,
                take_profit=pos.take_profit,
                quantity=pos.quantity,
                profit=profit,
                profit_pct=profit / (pos.entry_price * pos.quantity) if pos.entry_price > 0 and pos.quantity > 0 else 0,
                rr=round(rr, 2),
                result=result_type,
                exit_reason=f"SYNC_{exit_reason}",
            )
            demo_account.closed_trades.append(trade)

            # Remove from open positions
            del demo_account.open_positions[symbol]

            logger.info(
                f"[Sync] Closed {pos.side} {symbol} via exchange sync: "
                f"{result_type} ({exit_reason}) "
                f"Profit=${profit:.2f} RR={trade.rr:.2f}"
            )

        # Step 4: Mirror check — positions in DemoAccount not on exchange
        # This is handled by _run_crypto_analysis in api/main.py during signal processing.
        # We just log if there are positions that should be on exchange but aren't.
        for symbol in list(demo_account.open_positions.keys()):
            if symbol not in exchange_by_symbol:
                # Position exists in DemoAccount but not on exchange
                # The crypto analysis worker will handle this via the mirroring logic
                logger.info(
                    f"[Sync] {symbol} in DemoAccount but not on exchange — "
                    f"will be mirrored in next signal cycle"
                )
                result.positions_mirrored += 1

    except Exception as e:
        logger.error(f"[Sync] Sync cycle failed: {e}")
        result.errors.append(str(e))

    return result


# ── Background Worker ─────────────────────────────────────────────────

async def sync_worker(
    demo_account: DemoAccount,
    live_executor: LiveExecutor,
    latest_prices: Dict[str, float],
    health_dict: Dict,
    interval: int = SYNC_INTERVAL_SECONDS,
):
    """
    Background worker that periodically reconciles DemoAccount with exchange positions.
    Runs every `interval` seconds alongside the crypto data and HTF bias workers.

    Args:
        demo_account: The in-memory DemoAccount instance
        live_executor: The LiveExecutor connected to Binance
        latest_prices: Dict of {symbol: current_price}
        health_dict: Shared health dict for monitoring sync stats
        interval: Seconds between sync cycles
    """
    logger.info(f"[Sync] Worker started (interval={interval}s)")

    # Track total sync stats in health dict
    health_dict["sync_stats"] = {
        "total_cycles": 0,
        "total_closed_from_sl": 0,
        "total_closed_from_tp": 0,
        "total_closed_from_manual": 0,
        "total_errors": 0,
        "last_sync_time": None,
        "last_sync_result": None,
    }

    while True:
        try:
            await asyncio.sleep(interval)

            # Skip if no exchange
            if not live_executor or not live_executor.exchange:
                continue

            # Run sync
            result = await sync_positions(
                demo_account=demo_account,
                live_executor=live_executor,
                latest_prices=latest_prices,
            )

            # Update health stats
            stats = health_dict.get("sync_stats", {})
            stats["total_cycles"] = stats.get("total_cycles", 0) + 1
            stats["total_closed_from_sl"] += result.positions_closed_from_exchange_sl
            stats["total_closed_from_tp"] += result.positions_closed_from_exchange_tp
            stats["total_closed_from_manual"] += result.positions_closed_from_exchange_manual
            stats["total_errors"] += len(result.errors)
            stats["last_sync_time"] = result.timestamp.isoformat().replace("+00:00", "Z")
            stats["last_sync_result"] = {
                "demo_positions": result.demo_positions_checked,
                "exchange_positions": result.exchange_positions_checked,
                "closed_sl": result.positions_closed_from_exchange_sl,
                "closed_tp": result.positions_closed_from_exchange_tp,
                "closed_manual": result.positions_closed_from_exchange_manual,
                "discrepancies": len(result.discrepancies),
                "errors": len(result.errors),
            }

            # Log summary
            total_closed = (result.positions_closed_from_exchange_sl +
                           result.positions_closed_from_exchange_tp +
                           result.positions_closed_from_exchange_manual)
            if total_closed > 0 or len(result.discrepancies) > 0:
                logger.info(
                    f"[Sync] Cycle complete: {result.demo_positions_checked} demo positions checked, "
                    f"{result.exchange_positions_checked} exchange positions, "
                    f"{total_closed} closed via sync, "
                    f"{len(result.discrepancies)} discrepancies"
                )

        except asyncio.CancelledError:
            logger.info("[Sync] Worker cancelled.")
            break
        except Exception as e:
            logger.error(f"[Sync] Worker error: {e}")
            stats = health_dict.get("sync_stats", {})
            stats["total_errors"] = stats.get("total_errors", 0) + 1
