import React, { useState, useMemo } from 'react';
import ICTChart from '../components/ICTChart';
import { useQuery } from '@tanstack/react-query';
import { tradingApi } from '../services/api';

const CRYPTO_SYMBOLS = ['BTCUSDT', 'ETHUSDT'];
const FOREX_SYMBOLS = ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY'];
const ALL_SYMBOLS = [...CRYPTO_SYMBOLS, ...FOREX_SYMBOLS];
const TIMEFRAMES = ['1h', '5m', '15m'];

const _NOW = Math.floor(Date.now() / 1000);

const Charts: React.FC = () => {
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [timeframe, setTimeframe] = useState('1h');

  const isCrypto = CRYPTO_SYMBOLS.includes(symbol);
  const apiLimit = timeframe === '5m' ? 288 : timeframe === '15m' ? 96 : 200;

  const { data: apiCandles, isLoading } = useQuery({
    queryKey: ['candles', symbol, timeframe, apiLimit],
    queryFn: () => tradingApi.getCandles(symbol, timeframe, apiLimit),
    refetchInterval: 60_000,
  });

  // Stable mock fallback for forex pairs or when API is down
  const mockCandles = useMemo(() => {
    const base = symbol.startsWith('XAU') ? 2340 : symbol.startsWith('BTC') ? 68000 : symbol.startsWith('ETH') ? 3500 : 1.10;
    const range = symbol.startsWith('XAU') ? 10 : symbol.startsWith('BTC') ? 500 : symbol.startsWith('ETH') ? 50 : 0.01;
    const step = timeframe === '5m' ? 300 : timeframe === '15m' ? 900 : 3600;
    return Array.from({ length: 100 }, (_, i) => ({
      time: Math.floor(_NOW - (100 - i) * step) as any,
      open: base + Math.sin(i * 0.3) * range * 0.5,
      high: base + Math.sin(i * 0.3) * range * 0.5 + range * 0.3,
      low: base + Math.sin(i * 0.3) * range * 0.5 - range * 0.3,
      close: base + Math.sin(i * 0.3 + 0.2) * range * 0.5,
    }));
  }, [symbol, timeframe]);

  const displayData = useMemo(() => {
    if (apiCandles && apiCandles.length > 0) {
      return apiCandles.map(c => ({
        time: (new Date(c.timestamp).getTime() / 1000) as any,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }));
    }
    return mockCandles;
  }, [apiCandles, mockCandles]);

  return (
    <div className="space-y-6 h-full flex flex-col">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Market Analysis</h2>
        <div className="flex space-x-2">
          <select
            value={symbol}
            onChange={e => setSymbol(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded px-3 py-1 text-sm"
          >
            {ALL_SYMBOLS.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select
            value={timeframe}
            onChange={e => setTimeframe(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded px-3 py-1 text-sm"
          >
            {TIMEFRAMES.map(tf => (
              <option key={tf} value={tf}>{tf}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex-1 bg-slate-900 rounded-xl overflow-hidden min-h-[500px]">
        {isLoading ? (
          <div className="h-full flex items-center justify-center text-slate-500">
            Loading market data...
          </div>
        ) : (
          <ICTChart data={displayData} />
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-slate-900 p-4 border border-slate-800 rounded-xl">
          <h4 className="text-xs font-bold text-slate-500 uppercase mb-2">Symbol</h4>
          <div className="text-lg font-bold text-emerald-400">{symbol}</div>
          <div className="text-xs text-slate-500 mt-1">
            {isCrypto ? 'Real CoinGecko data' : 'Mock data (set TWELVEDATA_API_KEY for live)'}
          </div>
        </div>
        <div className="bg-slate-900 p-4 border border-slate-800 rounded-xl">
          <h4 className="text-xs font-bold text-slate-500 uppercase mb-2">Timeframe</h4>
          <div className="text-lg font-bold text-slate-300">{timeframe}</div>
          <div className="text-xs text-slate-500 mt-1">{displayData.length} candles</div>
        </div>
        <div className="bg-slate-900 p-4 border border-slate-800 rounded-xl">
          <h4 className="text-xs font-bold text-slate-500 uppercase mb-2">Data Source</h4>
          <div className={`text-lg font-bold ${isCrypto ? 'text-cyan-400' : 'text-amber-400'}`}>
            {isCrypto ? 'CoinGecko API' : 'Mock Data'}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {isCrypto ? 'Live cryptocurrency OHLC' : 'Forex requires Twelve Data API key'}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Charts;
