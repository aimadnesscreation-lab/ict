import axios from 'axios';
import type { Signal, Trade, PerformanceMetrics, DemoAccountData, RiskStatus, Candle, HealthStatus } from '../types';

const api = axios.create({ timeout: 8000 });
// No baseURL — all requests resolve relative to the current page origin.
// This works for both:
//   - Pre-built dashboard served by FastAPI (same origin: port 8000)
//   - Vite dev server at localhost:5173 (proxied by vite.config.ts)

// ── Fetch helpers ───────────────────────────────────────────────────────

async function fetch<T>(url: string, fallback: T): Promise<T> {
  try {
    const res = await api.get(url);
    return res.data as T;
  } catch {
    return fallback;
  }
}

// ── API client ──────────────────────────────────────────────────────────

export const tradingApi = {
  getSignals: (limit = 10): Promise<Signal[]> =>
    fetch(`/signals?limit=${limit}`, []),

  getSignalDetail: (signalId: number): Promise<Signal | null> =>
    fetch(`/signals/${signalId}`, null),

  getCandles: (symbol: string, timeframe = '1h', limit = 100): Promise<Candle[]> =>
    fetch(`/candles/${symbol}?timeframe=${timeframe}&limit=${limit}`, []),

  getTrades: (limit = 20, result?: string, symbol?: string): Promise<Trade[]> => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (result) params.set('result', result);
    if (symbol) params.set('symbol', symbol);
    return fetch(`/trades?${params}`, []);
  },

  getPerformance: (): Promise<PerformanceMetrics> =>
    fetch('/performance', {
      win_rate: 0, total_pnl: 0, profit_factor: 0,
      max_drawdown: 0, sharpe_ratio: 0, total_trades: 0, avg_rr: 0,
    }),

  getDemoAccount: (): Promise<DemoAccountData> =>
    fetch('/demo/account', {
      balance: 5000, initial_balance: 5000, total_profit: 0, total_trades: 0,
      win_rate: 0, profit_factor: 0, max_drawdown: 0, avg_rr: 0,
      total_wins: 0, total_losses: 0, peak_balance: 5000,
      current_drawdown_pct: 0, open_positions_count: 0, open_positions: [],
    }),

  getRiskStatus: (): Promise<RiskStatus> =>
    fetch('/risk/status', {
      max_risk_per_trade_pct: 1, max_daily_loss_pct: 3, max_weekly_loss_pct: 6,
      max_open_positions: 3, current_daily_loss_pct: 0, current_weekly_loss_pct: 0,
      open_positions_count: 0, account_balance: 5000,
    }),

  getHealth: (): Promise<HealthStatus> =>
    fetch('/api/health', {
      status: 'unknown', uptime: '', started_at: '', last_cycle_time: null,
      cycle_count: 0, htf_bias: 'neutral', total_signals_generated: 0,
      total_signals_kept: 0, total_trades_executed: 0, last_error_time: null,
      last_error_message: null, data_sources: [], eth_price: 0,
    }),

  resetAll: (): Promise<{ status: string; message: string }> =>
    api.post('/reset').then(r => r.data).catch(() => ({ status: 'error', message: 'Failed to reset' })),
};
