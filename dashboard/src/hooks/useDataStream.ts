import { useEffect, useRef, useState, useCallback } from 'react';
import type { Signal, Trade, DemoAccountData, RiskStatus, PerformanceMetrics, HealthStatus } from '../types';

interface DataSnapshot {
  signals: Signal[];
  trades: Trade[];
  demo_account: DemoAccountData;
  health: HealthStatus;
  risk_status: RiskStatus;
  performance: PerformanceMetrics;
}

interface DataStreamState {
  signals: Signal[];
  trades: Trade[];
  demo: DemoAccountData | null;
  health: HealthStatus | null;
  risk: RiskStatus | null;
  performance: PerformanceMetrics | null;
  connected: boolean;
  lastUpdate: number;
}

const WS_URL = import.meta.env.VITE_WS_URL ?? (() => {
  const apiUrl = import.meta.env.VITE_API_URL;
  if (apiUrl) {
    const parsed = new URL(apiUrl);
    const wsProto = parsed.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${wsProto}//${parsed.host}/ws/data`;
  }
  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${wsProto}//${window.location.host}/ws/data`;
})();

const API_BASE = import.meta.env.VITE_API_URL ?? '';
const RECONNECT_DELAY = 3000;
const MAX_RECONNECT_ATTEMPTS = 10;
const REST_POLL_INTERVAL = 15_000;

const EMPTY_DEMO: DemoAccountData = {
  balance: 5000, initial_balance: 5000, total_profit: 0, total_trades: 0,
  win_rate: 0, profit_factor: 0, max_drawdown: 0, avg_rr: 0,
  total_wins: 0, total_losses: 0, peak_balance: 5000,
  current_drawdown_pct: 0, open_positions_count: 0, open_positions: [],
};

const EMPTY_RISK: RiskStatus = {
  max_risk_per_trade_pct: 1, max_daily_loss_pct: 3, max_weekly_loss_pct: 6,
  max_open_positions: 3, current_daily_loss_pct: 0, current_weekly_loss_pct: 0,
  open_positions_count: 0, account_balance: 5000,
};

const EMPTY_PERF: PerformanceMetrics = {
  win_rate: 0, total_pnl: 0, profit_factor: 0,
  max_drawdown: 0, sharpe_ratio: 0, total_trades: 0, avg_rr: 0,
};

/** Fallback REST poller: fetches all data from REST endpoints every 15s */
async function pollREST(): Promise<Partial<DataSnapshot>> {
  const base = API_BASE;
  try {
    const [signalsRes, tradesRes, demoRes, healthRes, riskRes, perfRes] = await Promise.all([
      fetch(`${base}/signals?limit=50`).then(r => r.json()).catch(() => []),
      fetch(`${base}/trades?limit=200`).then(r => r.json()).catch(() => []),
      fetch(`${base}/demo/account`).then(r => r.json()).catch(() => EMPTY_DEMO),
      fetch(`${base}/api/health`).then(r => r.json()).catch(() => null),
      fetch(`${base}/risk/status`).then(r => r.json()).catch(() => EMPTY_RISK),
      fetch(`${base}/performance`).then(r => r.json()).catch(() => EMPTY_PERF),
    ]);
    return {
      signals: signalsRes ?? [],
      trades: tradesRes ?? [],
      demo_account: demoRes ?? EMPTY_DEMO,
      health: healthRes,
      risk_status: riskRes ?? EMPTY_RISK,
      performance: perfRes ?? EMPTY_PERF,
    };
  } catch {
    return {};
  }
}

export function useDataStream() {
  const [state, setState] = useState<DataStreamState>({
    signals: [], trades: [], demo: null, health: null,
    risk: null, performance: null, connected: false, lastUpdate: 0,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempt = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const restTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const connectRef = useRef<() => void>(undefined);
  const restFallbackRef = useRef(false);

  const startRESTFallback = useCallback(() => {
    if (restTimer.current) return;
    restFallbackRef.current = true;
    setState(prev => ({ ...prev, connected: false }));

    let wsRetryCycle = 0;

    // Initial fetch immediately
    pollREST().then(data => {
      if (data.signals || data.trades) {
        setState({
          signals: data.signals ?? [],
          trades: data.trades ?? [],
          demo: data.demo_account ?? EMPTY_DEMO,
          health: data.health ?? null,
          risk: data.risk_status ?? EMPTY_RISK,
          performance: data.performance ?? EMPTY_PERF,
          connected: false,
          lastUpdate: Date.now(),
        });
      }
    });

    // Poll every 15s, with periodic WS retry every 60s (4 cycles)
    restTimer.current = setInterval(async () => {
      const data = await pollREST();
      if (data.signals || data.trades) {
        setState(prev => ({
          ...prev,
          signals: data.signals ?? prev.signals,
          trades: data.trades ?? prev.trades,
          demo: data.demo_account ?? prev.demo,
          health: data.health ?? prev.health,
          risk: data.risk_status ?? prev.risk,
          performance: data.performance ?? prev.performance,
          lastUpdate: Date.now(),
        }));
      }

      // Every ~60s, try reconnecting WebSocket
      wsRetryCycle++;
      if (wsRetryCycle % 4 === 0) {
        reconnectAttempt.current = 0;
        connectRef.current?.();
      }
    }, REST_POLL_INTERVAL);
  }, []);

  const stopRESTFallback = useCallback(() => {
    if (restTimer.current) {
      clearInterval(restTimer.current);
      restTimer.current = null;
    }
    restFallbackRef.current = false;
  }, []);

  const cleanup = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      wsRef.current.close();
      wsRef.current = null;
    }
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    cleanup();

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttempt.current = 0;
        // If REST fallback is active, stop it when WS connects
        if (restFallbackRef.current) {
          stopRESTFallback();
        }
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'snapshot') {
            const snap = data as DataSnapshot;
            setState({
              signals: snap.signals ?? [],
              trades: snap.trades ?? [],
              demo: snap.demo_account ?? EMPTY_DEMO,
              health: snap.health ?? null,
              risk: snap.risk_status ?? EMPTY_RISK,
              performance: snap.performance ?? EMPTY_PERF,
              connected: true,
              lastUpdate: Date.now(),
            });
          }
        } catch {
          // Malformed message — skip
        }
      };

      ws.onclose = () => {
        setState(prev => ({ ...prev, connected: false }));
        wsRef.current = null;
        if (reconnectAttempt.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttempt.current += 1;
          const delay = RECONNECT_DELAY * Math.min(reconnectAttempt.current, 5);
          reconnectTimer.current = setTimeout(() => connectRef.current?.(), delay);
        } else {
          // Exhausted WS reconnect attempts — fall back to REST polling
          startRESTFallback();
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      // WebSocket constructor threw — use REST fallback immediately
      startRESTFallback();
    }
  }, [cleanup, startRESTFallback, stopRESTFallback]);

  useEffect(() => {
    connectRef.current = connect;
  });

  useEffect(() => {
    connect();
    return () => {
      cleanup();
      stopRESTFallback();
    };
  }, [connect, cleanup, stopRESTFallback]);

  return state;
}
