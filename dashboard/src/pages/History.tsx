import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { History as HistoryIcon, TrendingUp, TrendingDown, Activity, BarChart3, DollarSign, Percent } from 'lucide-react';
import { tradingApi } from '../services/api';

const pricePrecision = (symbol: string): number => 2;

const History: React.FC = () => {
  const [resultFilter, setResultFilter] = useState<string>('ALL');
  const [symbolFilter, setSymbolFilter] = useState<string>('ALL');

  const { data: trades = [], isLoading } = useQuery({
    queryKey: ['trades', 100],
    queryFn: () => tradingApi.getTrades(100),
    refetchInterval: 60_000,
  });

  const { data: perf } = useQuery({
    queryKey: ['performance'],
    queryFn: () => tradingApi.getPerformance(),
    refetchInterval: 60_000,
  });

  const symbols = useMemo(() => [...new Set(trades.map(t => t.symbol))].sort(), [trades]);

  const filtered = trades
    .filter(t => resultFilter === 'ALL' || t.result === resultFilter)
    .filter(t => symbolFilter === 'ALL' || t.symbol === symbolFilter);

  const stats = useMemo(() => {
    const wins = filtered.filter(t => t.result === 'WIN');
    const losses = filtered.filter(t => t.result === 'LOSS');
    const total = filtered.length;
    if (!total) return { winRate: 0, profit: 0, avgRr: 0, bestTrade: 0, worstTrade: 0 };
    return {
      winRate: wins.length / total,
      profit: filtered.reduce((s, t) => s + t.profit, 0),
      avgRr: filtered.reduce((s, t) => s + t.rr, 0) / total,
      bestTrade: Math.max(...filtered.map(t => t.profit), 0),
      worstTrade: Math.min(...filtered.map(t => t.profit), 0),
      wins: wins.length,
      losses: losses.length,
      total,
    };
  }, [filtered]);

  const formatCurrency = (v: number) =>
    (v >= 0 ? '+' : '') + v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const formatTime = (ts: string) => {
    const d = new Date(ts);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold flex items-center gap-3">
          <HistoryIcon className="text-cyan-400" size={28} />
          Trade History
        </h2>
        <div className="flex items-center gap-3">
          <select
            value={symbolFilter}
            onChange={e => setSymbolFilter(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm"
          >
            <option value="ALL">All Symbols</option>
            {symbols.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select
            value={resultFilter}
            onChange={e => setResultFilter(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm"
          >
            <option value="ALL">All Results</option>
            <option value="WIN">Wins</option>
            <option value="LOSS">Losses</option>
            <option value="BREAK_EVEN">Break Even</option>
          </select>
        </div>
      </div>

      {/* Performance stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 text-slate-500 text-xs font-bold uppercase mb-3">
            <Activity size={16} /> Win Rate
          </div>
          <div className="text-2xl font-bold">{(stats.winRate * 100).toFixed(1)}%</div>
          <div className="text-xs text-slate-500 mt-1">{stats.wins}W / {stats.losses}L</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 text-slate-500 text-xs font-bold uppercase mb-3">
            <DollarSign size={16} /> Total P&L
          </div>
          <div className={`text-2xl font-bold font-mono ${stats.profit >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            ${formatCurrency(stats.profit)}
          </div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 text-slate-500 text-xs font-bold uppercase mb-3">
            <BarChart3 size={16} /> Avg R:R
          </div>
          <div className="text-2xl font-bold">{stats.avgRr.toFixed(2)}</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 text-slate-500 text-xs font-bold uppercase mb-3">
            <Percent size={16} /> Profit Factor
          </div>
          <div className="text-2xl font-bold">{perf?.profit_factor.toFixed(2) ?? '—'}</div>
        </div>
      </div>

      {/* Trades table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <span className="text-sm text-slate-400">{filtered.length} trades</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-slate-950/50 text-slate-500 text-xs uppercase">
              <tr>
                <th className="px-6 py-3 font-medium">Symbol</th>
                <th className="px-6 py-3 font-medium">Direction</th>
                <th className="px-6 py-3 font-medium">Entry</th>
                <th className="px-6 py-3 font-medium">Exit</th>
                <th className="px-6 py-3 font-medium">Entry Time</th>
                <th className="px-6 py-3 font-medium">Exit Time</th>
                <th className="px-6 py-3 font-medium">P&L</th>
                <th className="px-6 py-3 font-medium">R:R</th>
                <th className="px-6 py-3 font-medium">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {isLoading ? (
                <tr><td colSpan={9} className="px-6 py-12 text-center text-slate-500">Loading trade history...</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={9} className="px-6 py-12 text-center text-slate-500">No trades match your filters.</td></tr>
              ) : filtered.map(trade => (
                <tr key={trade.id} className="hover:bg-slate-800/50 transition-colors">
                  <td className="px-6 py-4 font-bold">{trade.symbol}</td>
                  <td className="px-6 py-4">
                    <span className={`flex items-center gap-1 text-xs font-bold ${
                      trade.signal_type === 'BUY' ? 'text-emerald-400' : 'text-rose-400'
                    }`}>
                      {trade.signal_type === 'BUY' ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                      {trade.signal_type}
                    </span>
                  </td>
                  <td className="px-6 py-4 font-mono text-sm">{trade.entry_price.toFixed(pricePrecision(trade.symbol))}</td>
                  <td className="px-6 py-4 font-mono text-sm">{trade.exit_price.toFixed(pricePrecision(trade.symbol))}</td>
                  <td className="px-6 py-4 text-xs text-slate-400 whitespace-nowrap">{formatTime(trade.entry_time)}</td>
                  <td className="px-6 py-4 text-xs text-slate-400 whitespace-nowrap">{formatTime(trade.exit_time)}</td>
                  <td className="px-6 py-4">
                    <span className={`font-mono text-sm font-bold ${trade.profit > 0 ? 'text-emerald-400' : trade.profit < 0 ? 'text-rose-400' : 'text-slate-400'}`}>
                      ${formatCurrency(trade.profit)}
                    </span>
                  </td>
                  <td className="px-6 py-4 font-mono text-sm">{trade.rr.toFixed(2)}</td>
                  <td className="px-6 py-4">
                    <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${
                      trade.result === 'WIN' ? 'bg-emerald-500/10 text-emerald-400' :
                      trade.result === 'LOSS' ? 'bg-rose-500/10 text-rose-400' :
                      'bg-slate-500/10 text-slate-400'
                    }`}>
                      {trade.result === 'WIN' ? '✅ WIN' : trade.result === 'LOSS' ? '❌ LOSS' : '➖ BE'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Best / worst trade highlights */}
      {filtered.length > 0 && (
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-slate-900 border border-emerald-500/20 rounded-xl p-5">
            <div className="flex items-center gap-2 text-emerald-400 text-xs font-bold uppercase mb-2">
              <TrendingUp size={16} /> Best Trade
            </div>
            <div className="text-xl font-bold font-mono text-emerald-400">+${stats.bestTrade.toFixed(2)}</div>
          </div>
          <div className="bg-slate-900 border border-rose-500/20 rounded-xl p-5">
            <div className="flex items-center gap-2 text-rose-400 text-xs font-bold uppercase mb-2">
              <TrendingDown size={16} /> Worst Trade
            </div>
            <div className="text-xl font-bold font-mono text-rose-400">${stats.worstTrade.toFixed(2)}</div>
          </div>
        </div>
      )}
    </div>
  );
};

export default History;
