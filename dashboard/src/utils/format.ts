import clsx from 'clsx';

/** Formatting utilities for the dashboard */

export function formatCurrency(value: number, decimals = 2): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatPrice(_symbol: string, price: number): string {
  const decimals = price >= 1000 ? 2 : price >= 1 ? 4 : 6;
  return price.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatPnl(value: number): string {
  const prefix = value >= 0 ? '+' : '';
  return `${prefix}$${formatCurrency(Math.abs(value))}`;
}

export function formatTimeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function formatDateTime(timestamp: string): string {
  const d = new Date(timestamp);
  return d.toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export function formatPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

/** Classname utility: wraps clsx for conditional classes with objects support */
export function cn(...inputs: unknown[]): string {
  return clsx(inputs);
}

export function shortenSymbol(symbol: string): string {
  return symbol.replace('USDT', '').replace('USD', '');
}
