/** Shared types for the ICT Trading Dashboard */

export interface PriceTick {
  symbol: string;
  price: number;
  change_24h: number;
  high_24h: number;
  low_24h: number;
  volume: number;
  timestamp: string;
}

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
  in_kill_zone: boolean;
  meta_data: {
    sweep: boolean;
    sweep_type: string | null;
    bullish_fvg: boolean;
    bearish_fvg: boolean;
    fvg: boolean;
    discount: boolean;
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

export interface PerformanceMetrics {
  win_rate: number;
  total_pnl: number;
  profit_factor: number;
  max_drawdown: number;
  sharpe_ratio: number;
  total_trades: number;
  avg_rr: number;
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

export interface HealthStatus {
  status: string;
  uptime: string;
  started_at: string;
  last_cycle_time: string | null;
  cycle_count: number;
  htf_bias: string;
  total_signals_generated: number;
  total_signals_kept: number;
  total_trades_executed: number;
  last_error_time: string | null;
  last_error_message: string | null;
  data_sources: string[];
  eth_price: number;
}
