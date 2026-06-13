import { useEffect, useRef, useState, useCallback } from 'react';

export interface PriceTick {
  symbol: string;
  price: number;
  change_24h: number;
  high_24h: number;
  low_24h: number;
  volume: number;
  timestamp: string;
}

const WS_URL = 'ws://localhost:8000/ws/prices';
const RECONNECT_DELAY = 3000;
const MAX_RECONNECT_ATTEMPTS = 10;

// ── Fallback mock data generator (when WebSocket is unreachable) ──────

const FALLBACK_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY'];
const FALLBACK_BASE: Record<string, number> = {
  BTCUSDT: 68420, ETHUSDT: 3520, EURUSD: 1.1042, GBPUSD: 1.2654, XAUUSD: 2342.10, USDJPY: 151.24,
};
const FALLBACK_PRECISION: Record<string, number> = {
  BTCUSDT: 2, ETHUSDT: 2, EURUSD: 4, GBPUSD: 4, XAUUSD: 2, USDJPY: 3,
};

function generateMockTick(prices: Record<string, number>): PriceTick {
  const symbol = FALLBACK_SYMBOLS[Math.floor(Math.random() * FALLBACK_SYMBOLS.length)];
  const base = prices[symbol] ?? FALLBACK_BASE[symbol];
  const drift = base * (Math.random() - 0.5) * 0.0016;
  const prec = FALLBACK_PRECISION[symbol] ?? 4;
  const newPrice = Math.round((base + drift) * (10 ** prec)) / (10 ** prec);
  prices[symbol] = newPrice;
  return {
    symbol,
    price: newPrice,
    change_24h: Math.round((Math.random() * 6 - 3) * 100) / 100,
    high_24h: Math.round(base * 1.005 * (10 ** prec)) / (10 ** prec),
    low_24h: Math.round(base * 0.995 * (10 ** prec)) / (10 ** prec),
    volume: Math.round(Math.random() * 49000 + 1000),
    timestamp: new Date().toISOString(),
  };
}

// ── Hook ────────────────────────────────────────────────────────────────

export function usePriceStream() {
  const [prices, setPrices] = useState<Record<string, PriceTick>>({});
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempt = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mockTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const connectRef = useRef<() => void>();
  const fallbackPrices = useRef<Record<string, number>>({ ...FALLBACK_BASE });

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
    if (mockTimer.current) {
      clearInterval(mockTimer.current);
      mockTimer.current = null;
    }
  }, []);

  const startMockFallback = useCallback(() => {
    if (mockTimer.current) return;
    setConnected(false);
    FALLBACK_SYMBOLS.forEach(s => {
      fallbackPrices.current[s] = FALLBACK_BASE[s];
    });
    mockTimer.current = setInterval(() => {
      const tick = generateMockTick(fallbackPrices.current);
      setPrices(prev => ({ ...prev, [tick.symbol]: tick }));
    }, 1500);
  }, []);

  const connect = useCallback(() => {
    cleanup();

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        reconnectAttempt.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const tick: PriceTick = JSON.parse(event.data);
          setPrices(prev => ({ ...prev, [tick.symbol]: tick }));
        } catch {
          // Malformed message — skip
        }
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        if (reconnectAttempt.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttempt.current += 1;
          const delay = RECONNECT_DELAY * Math.min(reconnectAttempt.current, 5);
          reconnectTimer.current = setTimeout(() => connectRef.current?.(), delay);
        } else {
          startMockFallback();
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      startMockFallback();
    }
  }, [cleanup, startMockFallback]);

  useEffect(() => {
    // Keep connectRef synced so the onclose closure always calls the latest connect
    connectRef.current = connect;
  });

  useEffect(() => {
    connect();
    return cleanup;
  }, [connect, cleanup]);

  return { prices, connected };
}
