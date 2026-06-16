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

function generateMockSignals(count = 10): Signal[] {
  const symbols = ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY', 'BTCUSDT', 'ETHUSDT'];
  const types: Signal['signal_type'][] = ['STRONG_BUY', 'BUY', 'NEUTRAL', 'SELL', 'STRONG_SELL'];
  const weights = [15, 25, 20, 25, 15];
  const basePrices: Record<string, number> = {
    EURUSD: 1.1042, GBPUSD: 1.2654, XAUUSD: 2342.10,
    USDJPY: 151.24, BTCUSDT: 68420, ETHUSDT: 3520,
  };

  const weightedPick = () => {
    const total = weights.reduce((a, b) => a + b, 0);
    let r = Math.random() * total;
    for (let i = 0; i < types.length; i++) {
      r -= weights[i];
      if (r <= 0) return types[i];
    }
    return 'NEUTRAL' as Signal['signal_type'];
  };

  return Array.from({ length: count }, (_, i) => {
    const sym = symbols[Math.floor(Math.random() * symbols.length)];
    const bp = basePrices[sym] || 100;
    const score = Math.floor(Math.random() * 85) + 10;
    const bias = (['bullish', 'bearish', 'neutral'] as const)[Math.floor(Math.random() * 3)];
    const isBullish = Math.random() > 0.5;
    const bullScore = isBullish ? score : Math.floor(Math.random() * 30);
    const bearScore = isBullish ? Math.floor(Math.random() * 30) : score;
    return {
      id: i + 1,
      symbol: sym,
      signal_type: weightedPick(),
      score,
      bullish_score: bullScore,
      bearish_score: bearScore,
      net_score: bullScore - bearScore,
      price: Math.round((bp + (Math.random() - 0.5) * 10) * 10000) / 10000,
      timestamp: new Date(Date.now() - Math.random() * 86400000).toISOString(),
      confidence: Math.round((Math.random() * 0.48 + 0.5) * 100) / 100,
      timeframe: ['5m', '15m', '1h'][Math.floor(Math.random() * 3)],
      bias,
      meta_data: {
        mss: Math.random() > 0.4,
        mss_type: Math.random() > 0.5 ? (Math.random() > 0.5 ? 'BULLISH_MSS' : 'BEARISH_MSS') : null,
        sweep: Math.random() > 0.5,
        sweep_type: Math.random() > 0.5 ? (Math.random() > 0.5 ? 'BULLISH' : 'BEARISH') : null,
        bullish_fvg: Math.random() > 0.6,
        bearish_fvg: Math.random() > 0.7,
        bullish_ob: Math.random() > 0.65,
        bearish_ob: Math.random() > 0.7,
        fvg: Math.random() > 0.3,
        ob: Math.random() > 0.5,
        discount: Math.random() > 0.5,
        ote: Math.random() > 0.6,
        bias: bias,
        in_kill_zone: Math.random() > 0.6,
        htf_bias: bias,
        htf_aligned: true,
        active_sessions: ['london', 'new_york'].filter(() => Math.random() > 0.5),
        active_kill_zones: ['london_kill_zone'].filter(() => Math.random() > 0.7),
      },
    };
  });
}

function generateMockTrades(count = 20): Trade[] {
  const symbols = ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY', 'BTCUSDT'];
  const results: Trade['result'][] = ['WIN', 'WIN', 'WIN', 'LOSS', 'LOSS', 'BREAK_EVEN'];
  const basePrices: Record<string, number> = {
    EURUSD: 1.10, GBPUSD: 1.26, XAUUSD: 2340, USDJPY: 151, BTCUSDT: 68000,
  };

  return Array.from({ length: count }, (_, i) => {
    const sym = symbols[Math.floor(Math.random() * symbols.length)];
    const bp = basePrices[sym];
    const entry = Math.round((bp + (Math.random() - 0.5) * bp * 0.02) * 10000) / 10000;
    const result = results[Math.floor(Math.random() * results.length)];
    const isLong = Math.random() > 0.5;
    const rr = Math.round((Math.random() * 3 + 0.5) * 100) / 100;

    let profit: number;
    if (result === 'WIN') {
      profit = Math.round(entry * (Math.random() * 0.02 + 0.005) * 100) / 100;
    } else if (result === 'LOSS') {
      profit = -Math.round(entry * (Math.random() * 0.01 + 0.005) * 100) / 100;
    } else {
      profit = 0;
    }

    const entryTime = new Date(Date.now() - Math.random() * 604800000);
    const exitTime = new Date(entryTime.getTime() + Math.random() * 86400000);

    return {
      id: i + 1,
      symbol: sym,
      signal_type: isLong ? 'BUY' : 'SELL',
      entry_time: entryTime.toISOString(),
      exit_time: exitTime.toISOString(),
      entry_price: entry,
      exit_price: Math.round((entry + profit) * 10000) / 10000,
      profit: Math.round(profit * 100) / 100,
      rr: result === 'BREAK_EVEN' ? 0 : rr,
      result,
      exit_reason: result === 'WIN' ? 'TAKE_PROFIT' : result === 'LOSS' ? 'STOP_LOSS' : 'MANUAL',
    };
  }).sort((a, b) => new Date(b.exit_time).getTime() - new Date(a.exit_time).getTime());
}

function generateMockPerformance(): PerformanceMetrics {
  const trades = generateMockTrades(50);
  const wins = trades.filter(t => t.result === 'WIN');
  const losses = trades.filter(t => t.result === 'LOSS');
  const totalPnl = trades.reduce((s, t) => s + t.profit, 0);
  const grossProfits = wins.reduce((s, t) => s + t.profit, 0);
  const grossLosses = Math.abs(losses.reduce((s, t) => s + t.profit, 0));
  const winRate = trades.length ? wins.length / trades.length : 0;
  const avgRr = trades.length ? trades.reduce((s, t) => s + t.rr, 0) / trades.length : 0;
  const avgReturn = trades.length ? trades.reduce((s, t) => s + t.profit / t.entry_price, 0) / trades.length : 0;

  return {
    win_rate: Math.round(winRate * 10000) / 10000,
    total_pnl: Math.round(totalPnl * 100) / 100,
    profit_factor: grossLosses > 0 ? Math.round((grossProfits / grossLosses) * 100) / 100 : grossProfits > 0 ? 999 : 0,
    max_drawdown: Math.round(Math.random() * 0.05 * 10000) / 10000,
    sharpe_ratio: Math.round((avgReturn / 0.01) * Math.sqrt(252) * 100) / 100,
    total_trades: trades.length,
    avg_rr: Math.round(avgRr * 100) / 100,
  };
}

function generateMockRiskStatus(): RiskStatus {
  return {
    max_risk_per_trade_pct: 1.0,
    max_daily_loss_pct: 3.0,
    max_weekly_loss_pct: 6.0,
    max_open_positions: 3,
    current_daily_loss_pct: 0.4,
    current_weekly_loss_pct: 1.2,
    open_positions_count: 1,
    account_balance: 10000.0,
  };
}

// ── API Client ──────────────────────────────────────────────────────────

async function safeRequest<T>(fn: () => Promise<T>, fallback: T, label: string): Promise<T> {
  try {
    return await fn();
  } catch {
    console.warn(`API unreachable for "${label}", using fallback data`);
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

  getSignalDetail: (signalId: number): Promise<Signal> =>
    safeRequest(
      async () => {
        const res = await api.get(`/signals/${signalId}`);
        return res.data;
      },
      generateMockSignals(50).find(s => s.id === signalId) ?? generateMockSignals(1)[0],
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
        balance: 10000,
        initial_balance: 10000,
        total_profit: 0,
        total_trades: 0,
        win_rate: 0,
        profit_factor: 0,
        max_drawdown: 0,
        avg_rr: 0,
        total_wins: 0,
        total_losses: 0,
        peak_balance: 10000,
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
