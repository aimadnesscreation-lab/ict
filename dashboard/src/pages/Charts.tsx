import React from 'react';
import ICTChart from '../components/ICTChart';
import { useQuery } from '@tanstack/react-query';
import { tradingApi } from '../services/api';

const Charts: React.FC = () => {
  const { data: candles, isLoading } = useQuery({
    queryKey: ['candles', 'EURUSD'],
    queryFn: () => tradingApi.getCandles('EURUSD', '1h', 200),
  });

  // Mock data for initial load if API is not running
  const mockCandles = Array.from({ length: 100 }, (_, i) => ({
    time: (Date.now() / 1000 - (100 - i) * 3600) as any,
    open: 1.1000 + Math.random() * 0.01,
    high: 1.1100 + Math.random() * 0.01,
    low: 1.0900 + Math.random() * 0.01,
    close: 1.1050 + Math.random() * 0.01,
  }));

  const displayData = candles && candles.length > 0 ? candles.map(c => ({
    time: (new Date(c.timestamp).getTime() / 1000) as any,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close
  })) : mockCandles;

  return (
    <div className="space-y-6 h-full flex flex-col">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Market Analysis</h2>
        <div className="flex space-x-2">
          <select className="bg-slate-900 border border-slate-800 rounded px-3 py-1 text-sm">
            <option>EURUSD</option>
            <option>GBPUSD</option>
          </select>
          <select className="bg-slate-900 border border-slate-800 rounded px-3 py-1 text-sm">
            <option>1H</option>
            <option>15M</option>
            <option>5M</option>
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
          <h4 className="text-xs font-bold text-slate-500 uppercase mb-2">Current Zone</h4>
          <div className="text-lg font-bold text-emerald-400">Discount Zone</div>
        </div>
        <div className="bg-slate-900 p-4 border border-slate-800 rounded-xl">
          <h4 className="text-xs font-bold text-slate-500 uppercase mb-2">Liquidity</h4>
          <div className="text-lg font-bold text-slate-300">PDH Untouched</div>
        </div>
        <div className="bg-slate-900 p-4 border border-slate-800 rounded-xl">
          <h4 className="text-xs font-bold text-slate-500 uppercase mb-2">Trend Bias</h4>
          <div className="text-lg font-bold text-cyan-400">Bullish BOS (H4)</div>
        </div>
      </div>
    </div>
  );
};

export default Charts;
