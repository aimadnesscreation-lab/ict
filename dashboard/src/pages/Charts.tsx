import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { tradingApi } from '../services/api';
import { usePriceStream } from '../hooks/usePriceStream';
import { cn, formatPrice, shortenSymbol } from '../utils/format';
import ICTChart from '../components/ICTChart';
import EMABiasChart from '../components/EMABiasChart';
import type { CandlestickData, Time } from 'lightweight-charts';

const SYMBOLS = ['ETHUSDT'];
const TIMEFRAMES = ['1h', '5m', '15m'];

export default function Charts() {
  const [symbol, setSymbol] = useState('ETHUSDT');
  const [timeframe, setTimeframe] = useState('1h');
  const { prices } = usePriceStream();

  const limit = timeframe === '5m' ? 288 : timeframe === '15m' ? 168 : 200;

  const { data: candles = [], isLoading } = useQuery({
    queryKey: ['candles', symbol, timeframe, limit],
    queryFn: () => tradingApi.getCandles(symbol, timeframe, limit),
    refetchInterval: 15_000,
  });

  const [initialTime] = useState(() => Math.floor(Date.now() / 1000));

  const chartData = useMemo((): CandlestickData[] => {
    if (candles.length > 0) {
      return candles.map(c => ({
        time: Math.floor(new Date(c.timestamp).getTime() / 1000) as Time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }));
    }
    // Fallback mock
    const now = initialTime;
    const base = 3500;
    const range = 50;
    const step = timeframe === '5m' ? 300 : timeframe === '15m' ? 900 : 3600;
    return Array.from({ length: 100 }, (_, i) => ({
      time: (now - (100 - i) * step) as Time,
      open: base + Math.sin(i * 0.3) * range * 0.5,
      high: base + Math.sin(i * 0.3) * range * 0.5 + range * 0.3,
      low: base + Math.sin(i * 0.3) * range * 0.5 - range * 0.3,
      close: base + Math.sin(i * 0.3 + 0.2) * range * 0.5,
    }));
  }, [candles, symbol, timeframe, initialTime]);

  const tick = prices[symbol];
  const currentPrice = tick?.price ?? (chartData.length > 0 ? chartData[chartData.length - 1].close : 0);
  const change24h = tick?.change_24h ?? 0;

  return (
    <div className="space-y-6 h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-2xl font-bold">Market Analysis</h2>
        <div className="flex gap-2">
          <select value={symbol} onChange={e => setSymbol(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500/50">
            {SYMBOLS.map(s => <option key={s} value={s}>{shortenSymbol(s)}</option>)}
          </select>
          <select value={timeframe} onChange={e => setTimeframe(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500/50">
            {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
          </select>
        </div>
      </div>

      {/* Live price strip */}
      <div className="flex items-center gap-6 px-5 py-3 bg-slate-900 border border-slate-800 rounded-xl">
        <div>
          <div className="text-xs text-slate-500">{shortenSymbol(symbol)}</div>
          <div className="text-xl font-bold font-mono">${formatPrice(symbol, currentPrice)}</div>
        </div>
        <div>
          <div className="text-xs text-slate-500">24h Change</div>
          <div className={cn('text-lg font-bold', change24h >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
            {change24h >= 0 ? '+' : ''}{change24h.toFixed(2)}%
          </div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Timeframe</div>
          <div className="text-lg font-bold">{timeframe}</div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Candles</div>
          <div className="text-lg font-bold">{chartData.length}</div>
        </div>
        <div className="ml-auto text-xs text-slate-600">
          {candles.length > 0 ? 'Binance API' : 'Mock data'}
        </div>
      </div>

      {/* Candlestick Chart */}
      <div className="flex-1 bg-slate-900 rounded-xl overflow-hidden min-h-[450px] border border-slate-800">
        {isLoading && candles.length === 0 ? (
          <div className="h-full flex items-center justify-center text-slate-500">Loading market data...</div>
        ) : (
          <ICTChart data={chartData} symbol={symbol} />
        )}
      </div>

      {/* EMA Bias (1h only) */}
      {timeframe === '1h' && chartData.length >= 26 && (
        <EMABiasChart data={chartData as { time: number; close: number }[]} />
      )}
    </div>
  );
}
