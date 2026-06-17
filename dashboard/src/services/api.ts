import axios from 'axios';

// When served from the same origin as the API (Railway), use a relative path.
// For local dev, set VITE_API_URL to http://localhost:8000 or your Railway URL.
const API_BASE_URL = import.meta.env.VITE_API_URL ?? '';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 5000,
});

// ── Types ────────────────────────────────────────────────────────────────

export interface Signal {
  id: number;
  symbol: string;
  signal_type: 'STRONG_BUY' | 'BUY' | 'NEUTRAL' | 'SELL' | 'STRONG_SELL';
  score: number;
  bullish_score: number;
  bearish_score: number;
  net_score: number;
  price: number;
  timeframe: string;
  bias: 'bullish' | 'bearish' | 'neutral';
  timestamp: string;
  confidence: number;
  meta_data: {
    mss: boolean;
    mss_type: string | null;
    sweep: boolean;
    sweep_type: string | null;
    bullish_fvg: boolean;
    bearish_fvg: boolean;
    bullish_ob: boolean;
    bearish_ob: boolean;
    fvg: boolean;
    ob: boolean;
    discount: boolean;
    ote: boolean;
    bias: string;
    in_kill_zone: boolean;
    htf_bias: string;
    htf_aligned: boolean;
    active_sessions: string[];
    active_kill_zones: string[];
  };
}

export interface Trade {
  id: number;
  symbol: string;
  signal_type: string;
  entry_time: string;
  exit_time: string;
  entry_price: number;
  exit_price: number;
  profit: number;
  rr: number;
  result: 'WIN' | 'LOSS' | 'BREAK_EVEN';
  exit_reason: string;
}

export interface PerformanceMetrics {
  win_rate: number;
  total_pnl: number;
  profit_factor: number;
  max_drawdown: number;
  sharpe_ratio: number;
  total_trades: number;
  avg_rr: number;
}

export interface OpenPosition {
  symbol: string;
  side: 'LONG' | 'SHORT';
  signal_type: string;
  entry_time: string;
  entry_price: number;
  current_price: number;
  stop_loss: number;
  take_profit: number;
  quantity: number;
  risk_amount: number;
  unrealized_pnl: number;
}

export interface DemoAccountData {
  balance: number;
  initial_balance: number;
  total_profit: number;
  total_trades: number;
  win_rate: number;
  profit_factor: number;
  max_drawdown: number;
  avg_rr: number;
  total_wins: number;
  total_losses: number;
  peak_balance: number;
  current_drawdown_pct: number;
  open_positions_count: number;
  open_positions: OpenPosition[];
}

export interface RiskStatus {
  max_risk_per_trade_pct: number;
  max_daily_loss_pct: number;
  max_weekly_loss_pct: number;
  max_open_positions: number;
  current_daily_loss_pct: number;
  current_weekly_loss_pct: number;
  open_positions_count: number;
  account_balance: number;
}

export interface Candle {
  id: number;
  symbol: string;
  timeframe: string;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ── Mock fallback data (used when API is unreachable) ───────────────────


function generateMockSignals(_count = 10): Signal[] {
  return [];
}

function generateMockTrades(_count = 20): Trade[] {
  return [];
}

function generateMockPerformance(): PerformanceMetrics {
  return {
    win_rate: 0,
    total_pnl: 0,
    profit_factor: 0,
    max_drawdown: 0,
    sharpe_ratio: 0,
    total_trades: 0,
    avg_rr: 0,
  };
}

function generateMockRiskStatus(): RiskStatus {
  return {
    max_risk_per_trade_pct: 1.0,
    max_daily_loss_pct: 3.0,
    max_weekly_loss_pct: 6.0,
    max_open_positions: 3,
    current_daily_loss_pct: 0.0,
    current_weekly_loss_pct: 0.0,
    open_positions_count: 0,
    account_balance: 5000.0,
  };
}

// ── API Client ──────────────────────────────────────────────────────────

async function safeRequest<T>(fn: () => Promise<T>, fallback: T, label: string): Promise<T> {
  try {
    return await fn();
  } catch {
    const apiUrl = import.meta.env.VITE_API_URL || '(same origin — Vite default)';
    console.warn(`[API] "${label}" failed (trying ${apiUrl}). Showing empty state.`);
    console.warn(`[API] Fix: run the dashboard with: VITE_API_URL=http://localhost:8000 npm run dev`);
    console.warn(`[API] Or access the dashboard at http://localhost:8000/dashboard (no env var needed)`);
    return fallback;
  }
}

export const tradingApi = {
  getSignals: (limit = 10): Promise<Signal[]> =>
    safeRequest(
      async () => {
        const res = await api.get(`/signals?limit=${limit}`);
        return res.data;
      },
      generateMockSignals(limit),
      'getSignals',
    ),

  getSignalDetail: (signalId: number): Promise<Signal | null> =>
    safeRequest(
      async () => {
        const res = await api.get(`/signals/${signalId}`);
        return res.data;
      },
      null,
      'getSignalDetail',
    ),

  getCandles: (symbol: string, timeframe = '1h', limit = 100): Promise<Candle[]> =>
    safeRequest(
      async () => {
        const res = await api.get(`/candles/${symbol}?timeframe=${timeframe}&limit=${limit}`);
        return res.data;
      },
      [],
      'getCandles',
    ),

  getTrades: (limit = 20, result?: string, symbol?: string): Promise<Trade[]> =>
    safeRequest(
      async () => {
        const params = new URLSearchParams({ limit: String(limit) });
        if (result) params.set('result', result);
        if (symbol) params.set('symbol', symbol);
        const res = await api.get(`/trades?${params}`);
        return res.data;
      },
      generateMockTrades(limit),
      'getTrades',
    ),

  getPerformance: (): Promise<PerformanceMetrics> =>
    safeRequest(
      async () => {
        const res = await api.get('/performance');
        return res.data;
      },
      generateMockPerformance(),
      'getPerformance',
    ),

  getDemoAccount: (): Promise<DemoAccountData> =>
    safeRequest(
      async () => {
        const res = await api.get('/demo/account');
        return res.data;
      },
      {
        balance: 5000,
        initial_balance: 5000,
        total_profit: 0,
        total_trades: 0,
        win_rate: 0,
        profit_factor: 0,
        max_drawdown: 0,
        avg_rr: 0,
        total_wins: 0,
        total_losses: 0,
        peak_balance: 5000,
        current_drawdown_pct: 0,
        open_positions_count: 0,
        open_positions: [],
      },
      'getDemoAccount',
    ),

  getRiskStatus: (): Promise<RiskStatus> =>
    safeRequest(
      async () => {
        const res = await api.get('/risk/status');
        return res.data;
      },
      generateMockRiskStatus(),
      'getRiskStatus',
    ),
};
