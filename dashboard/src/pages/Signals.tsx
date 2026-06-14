import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Search, ChevronDown, ChevronUp, Radio, Activity, TrendingUp, TrendingDown, Minus, X } from 'lucide-react';

// Mirror of api/main.py FOREX_PRECISION for frontend price display
const FOREX_PRECISION: Record<string, number> = {
  EURUSD: 4, GBPUSD: 4, XAUUSD: 2, USDJPY: 3,
};

const _NOW = Date.now();
import { tradingApi } from '../services/api';
import type { Signal } from '../services/api';

const typeColors: Record<string, { bg: string; text: string; border: string }> = {
  STRONG_BUY: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', border: 'border-emerald-500/30' },
  BUY: { bg: 'bg-emerald-500/5', text: 'text-emerald-300', border: 'border-emerald-500/20' },
  NEUTRAL: { bg: 'bg-slate-500/10', text: 'text-slate-400', border: 'border-slate-500/30' },
  SELL: { bg: 'bg-rose-500/5', text: 'text-rose-300', border: 'border-rose-500/20' },
  STRONG_SELL: { bg: 'bg-rose-500/10', text: 'text-rose-400', border: 'border-rose-500/30' },
};

const Signals: React.FC = () => {
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<string>('ALL');
  const [sortBy, setSortBy] = useState<'timestamp' | 'score'>('timestamp');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [selectedSignal, setSelectedSignal] = useState<Signal | null>(null);

  const { data: signals = [], isLoading } = useQuery({
    queryKey: ['signals', 50],
    queryFn: () => tradingApi.getSignals(50),
    refetchInterval: 30_000,
  });

  const filtered = signals
    .filter(s => s.symbol.toUpperCase().includes(search.toUpperCase()))
    .filter(s => typeFilter === 'ALL' || s.signal_type === typeFilter)
    .sort((a, b) => {
      const mul = sortDir === 'asc' ? 1 : -1;
      if (sortBy === 'timestamp') return mul * (new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
      return mul * (a.score - b.score);
    });

  const toggleSort = (field: typeof sortBy) => {
    if (sortBy === field) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortBy(field); setSortDir('desc'); }
  };

  const formatTime = (ts: string) => {
    const diff = _NOW - new Date(ts).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  };

  return (
    <div className="space-y-6 h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold flex items-center gap-3">
          <Radio className="text-emerald-400" size={28} />
          Signals
        </h2>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" size={16} />
            <input
              type="text"
              placeholder="Search symbol..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="bg-slate-900 border border-slate-800 rounded-lg pl-10 pr-4 py-2 text-sm w-48 focus:outline-none focus:border-emerald-500/50 transition-colors"
            />
          </div>
          <select
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500/50"
          >
            <option value="ALL">All Types</option>
            <option value="STRONG_BUY">Strong Buy</option>
            <option value="BUY">Buy</option>
            <option value="NEUTRAL">Neutral</option>
            <option value="SELL">Sell</option>
            <option value="STRONG_SELL">Strong Sell</option>
          </select>
        </div>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-4 gap-4">
        {(['STRONG_BUY', 'BUY', 'SELL', 'STRONG_SELL'] as const).map(type => {
          const count = signals.filter(s => s.signal_type === type).length;
          const tc = typeColors[type];
          return (
            <div key={type} className={`${tc.bg} ${tc.border} border rounded-xl p-4`}>
              <div className={`text-xs font-bold uppercase ${tc.text} mb-1`}>{type.replace('_', ' ')}</div>
              <div className="text-2xl font-bold text-slate-100">{count}</div>
            </div>
          );
        })}
      </div>

      {/* Main content */}
      <div className="flex-1 flex gap-6 min-h-0">
        {/* Signals table */}
        <div className={`bg-slate-900 border border-slate-800 rounded-xl overflow-hidden ${selectedSignal ? 'w-3/5' : 'w-full'}`}>
          <div className="overflow-auto max-h-full">
            <table className="w-full text-left">
              <thead className="bg-slate-950/50 text-slate-500 text-xs uppercase sticky top-0">
                <tr>
                  <th className="px-6 py-3 font-medium">Symbol</th>
                  <th className="px-6 py-3 font-medium">TF</th>
                  <th className="px-6 py-3 font-medium">Type</th>
                  <th className="px-6 py-3 font-medium">Bias</th>
                  <th
                    className="px-6 py-3 font-medium cursor-pointer hover:text-slate-300 select-none"
                    onClick={() => toggleSort('score')}
                  >
                    <span className="flex items-center gap-1">
                      Score
                      {sortBy === 'score' && (sortDir === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />)}
                    </span>
                  </th>
                  <th className="px-6 py-3 font-medium">Confidence</th>
                  <th className="px-6 py-3 font-medium">Price</th>
                  <th
                    className="px-6 py-3 font-medium cursor-pointer hover:text-slate-300 select-none"
                    onClick={() => toggleSort('timestamp')}
                  >
                    <span className="flex items-center gap-1">
                      Time
                      {sortBy === 'timestamp' && (sortDir === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />)}
                    </span>
                  </th>
                  <th className="px-6 py-3 font-medium">Confluences</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {isLoading ? (
                  <tr><td colSpan={9} className="px-6 py-12 text-center text-slate-500">Loading signals...</td></tr>
                ) : filtered.length === 0 ? (
                  <tr><td colSpan={9} className="px-6 py-12 text-center text-slate-500">No signals match your filters.</td></tr>
                ) : filtered.map(signal => (
                  <tr
                    key={signal.id}
                    onClick={() => setSelectedSignal(selectedSignal?.id === signal.id ? null : signal)}
                    className={`hover:bg-slate-800/50 transition-colors cursor-pointer ${
                      selectedSignal?.id === signal.id ? 'bg-slate-800/80' : ''
                    }`}
                  >
                    <td className="px-6 py-4 font-bold">{signal.symbol}</td>
                    <td className="px-6 py-4">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                        signal.timeframe === '5m' ? 'bg-amber-500/20 text-amber-400'
                          : signal.timeframe === '15m' ? 'bg-cyan-500/20 text-cyan-400'
                          : 'bg-emerald-500/20 text-emerald-400'
                      }`}>
                        {signal.timeframe}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${typeColors[signal.signal_type].text} ${typeColors[signal.signal_type].bg}`}>
                        {signal.signal_type.replace('_', ' ')}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`text-xs font-bold ${
                        signal.bias === 'bullish' ? 'text-emerald-400'
                          : signal.bias === 'bearish' ? 'text-rose-400'
                          : 'text-slate-500'
                      }`}>
                        {signal.bias === 'bullish' ? '📈' : signal.bias === 'bearish' ? '📉' : '➖'} {signal.bias.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-bold">{signal.score}</span>
                        <div className="w-16 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all ${
                              signal.score >= 60 ? 'bg-emerald-500' : signal.score >= 40 ? 'bg-amber-500' : 'bg-rose-500'
                            }`}
                            style={{ width: `${signal.score}%` }}
                          />
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className="font-mono text-sm">{Math.round(signal.confidence * 100)}%</span>
                    </td>
                    <td className="px-6 py-4 font-mono text-sm">
                      {signal.price.toFixed(FOREX_PRECISION[signal.symbol] ?? 2)}
                    </td>
                    <td className="px-6 py-4 text-slate-500 text-xs whitespace-nowrap">{formatTime(signal.timestamp)}</td>
                    <td className="px-6 py-4">
                      <div className="flex gap-1.5">
                        <ConfluenceBadge active={signal.meta_data.mss} label="MSS" />
                        <ConfluenceBadge active={signal.meta_data.sweep} label="SWP" />
                        <ConfluenceBadge active={signal.meta_data.fvg} label="FVG" />
                        <ConfluenceBadge active={signal.meta_data.ob} label="OB" />
                        <ConfluenceBadge active={signal.meta_data.discount} label="DIS" />
                        <ConfluenceBadge active={signal.meta_data.ote} label="OTE" />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Detail panel */}
        {selectedSignal && (
          <div className="w-2/5 bg-slate-900 border border-slate-800 rounded-xl p-6 overflow-auto">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold">Signal Detail</h3>
              <button onClick={() => setSelectedSignal(null)} className="text-slate-500 hover:text-slate-300 transition-colors">
                <X size={20} />
              </button>
            </div>

            <div className="space-y-6">
              {/* Header */}
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-2xl font-bold">{selectedSignal.symbol}</div>
                  <div className={`text-sm font-bold ${typeColors[selectedSignal.signal_type].text}`}>
                    {selectedSignal.signal_type.replace('_', ' ')}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-bold font-mono">
                    {selectedSignal.price.toFixed(FOREX_PRECISION[selectedSignal.symbol] ?? 2)}
                  </div>
                  <div className="text-xs text-slate-500">
                    {new Date(selectedSignal.timestamp).toLocaleString()}
                  </div>
                </div>
              </div>

              {/* Score gauge */}
              <div className="bg-slate-950 rounded-xl p-5 border border-slate-800">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm text-slate-400">Signal Score</span>
                  <span className={`text-3xl font-bold font-mono ${
                    selectedSignal.score >= 60 ? 'text-emerald-400' : selectedSignal.score >= 40 ? 'text-amber-400' : 'text-rose-400'
                  }`}>
                    {selectedSignal.score}
                  </span>
                </div>
                <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      selectedSignal.score >= 60 ? 'bg-emerald-500' : selectedSignal.score >= 40 ? 'bg-amber-500' : 'bg-rose-500'
                    }`}
                    style={{ width: `${selectedSignal.score}%` }}
                  />
                </div>
                <div className="flex justify-between text-xs text-slate-600 mt-1">
                  <span>0</span>
                  <span>50</span>
                  <span>100</span>
                </div>
              </div>

              {/* Timeframe + Bias */}
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-slate-950 rounded-xl p-4 border border-slate-800">
                  <h4 className="text-sm font-bold text-slate-400 mb-2">Timeframe</h4>
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] font-bold px-2 py-1 rounded ${
                      selectedSignal.timeframe === '5m' ? 'bg-amber-500/20 text-amber-400'
                        : selectedSignal.timeframe === '15m' ? 'bg-cyan-500/20 text-cyan-400'
                        : 'bg-emerald-500/20 text-emerald-400'
                    }`}>
                      {selectedSignal.timeframe}
                    </span>
                    <span className="text-xs text-slate-500">candle</span>
                  </div>
                </div>
                <div className="bg-slate-950 rounded-xl p-4 border border-slate-800">
                  <h4 className="text-sm font-bold text-slate-400 mb-2">Trend Bias</h4>
                  <div className={`text-lg font-bold ${
                    selectedSignal.bias === 'bullish' ? 'text-emerald-400'
                      : selectedSignal.bias === 'bearish' ? 'text-rose-400'
                      : 'text-slate-400'
                  }`}>
                    {selectedSignal.bias === 'bullish' ? '📈' : selectedSignal.bias === 'bearish' ? '📉' : '➖'} {selectedSignal.bias.toUpperCase()}
                  </div>
                </div>
              </div>

              {/* Confluences */}
              <div>
                <h4 className="text-sm font-bold text-slate-400 mb-3 uppercase tracking-wide">Confluences</h4>
                <div className="grid grid-cols-2 gap-3">
                  <ConfluenceCard active={selectedSignal.meta_data.mss} label="Market Structure Shift" points={20} />
                  <ConfluenceCard active={selectedSignal.meta_data.sweep} label="Liquidity Sweep" points={20} />
                  <ConfluenceCard active={selectedSignal.meta_data.fvg} label="Fair Value Gap" points={15} />
                  <ConfluenceCard active={selectedSignal.meta_data.ob} label="Order Block" points={15} />
                  <ConfluenceCard active={selectedSignal.meta_data.discount} label="Discount Zone" points={10} />
                  <ConfluenceCard active={selectedSignal.meta_data.ote} label="OTE Zone" points={10} />
                </div>
              </div>

              {/* News Sentiment */}
              <div className="bg-slate-950 rounded-xl p-4 border border-slate-800">
                <h4 className="text-sm font-bold text-slate-400 mb-2">News Sentiment</h4>
                <div className="flex items-center gap-3">
                  {selectedSignal.meta_data.news_sentiment > 0.3 ? (
                    <TrendingUp className="text-emerald-400" size={24} />
                  ) : selectedSignal.meta_data.news_sentiment < -0.3 ? (
                    <TrendingDown className="text-rose-400" size={24} />
                  ) : (
                    <Minus className="text-slate-400" size={24} />
                  )}
                  <span className={`text-2xl font-bold font-mono ${
                    selectedSignal.meta_data.news_sentiment > 0 ? 'text-emerald-400' : 'text-rose-400'
                  }`}>
                    {selectedSignal.meta_data.news_sentiment > 0 ? '+' : ''}{selectedSignal.meta_data.news_sentiment.toFixed(2)}
                  </span>
                </div>
              </div>

              {/* Confidence */}
              <div className="bg-slate-950 rounded-xl p-4 border border-slate-800">
                <h4 className="text-sm font-bold text-slate-400 mb-2">Model Confidence</h4>
                <div className="flex items-center gap-2">
                  <Activity className="text-cyan-400" size={20} />
                  <span className="text-2xl font-bold">{Math.round(selectedSignal.confidence * 100)}%</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const ConfluenceBadge = ({ active, label }: { active: boolean; label: string }) => (
  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
    active ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-800 text-slate-600'
  }`}>
    {label}
  </span>
);

const ConfluenceCard = ({ active, label, points }: { active: boolean; label: string; points: number }) => (
  <div className={`rounded-xl p-3 border ${active ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-slate-950 border-slate-800 opacity-50'}`}>
    <div className="flex items-center justify-between mb-1">
      <span className="text-xs font-medium text-slate-400">{label}</span>
      {active ? <span className="text-emerald-400 text-xs font-bold">+{points}</span> : <span className="text-slate-600 text-xs">—</span>}
    </div>
    <div className="text-lg">{active ? '✅' : '❌'}</div>
  </div>
);

export default Signals;
