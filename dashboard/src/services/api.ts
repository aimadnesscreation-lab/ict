import axios from 'axios';

const API_BASE_URL = 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
});

export interface Signal {
  id: number;
  symbol: string;
  signal_type: string;
  score: number;
  timestamp: string;
  price: number;
  meta_data: any;
}

export interface PerformanceMetrics {
  win_rate: number;
  total_pnl: number;
  profit_factor: number;
  max_drawdown: number;
  sharpe_ratio: number;
  total_trades: number;
}

export const tradingApi = {
  getSignals: async (limit = 10): Promise<Signal[]> => {
    const response = await api.get(`/signals?limit=${limit}`);
    return response.data;
  },
  getPerformance: async (): Promise<PerformanceMetrics> => {
    const response = await api.get('/performance');
    return response.data;
  },
  getCandles: async (symbol: string, timeframe = '1h', limit = 100): Promise<any[]> => {
    const response = await api.get(`/candles/${symbol}?timeframe=${timeframe}&limit=${limit}`);
    return response.data;
  },
  getRiskStatus: async (): Promise<any> => {
    const response = await api.get('/risk/status');
    return response.data;
  }
};
