import { useState, useMemo } from 'react';
import { Search, ChevronDown, ChevronUp, Radio, X, Activity } from 'lucide-react';
import { useDataStream } from '../hooks/useDataStream';
import SignalBadge from '../components/SignalBadge';
import { formatTimeAgo, cn, shortenSymbol } from '../utils/format';
import type { Signal } from '../types';

const typeColors: Record<string, string> = {
  STRONG_BUY: 'text-emerald-400', BUY: 'text-emerald-300',
  NEUTRAL: 'text-slate-400', SELL: 'text-rose-300', STRONG_SELL: 'text-rose-400',
};

export default function Signals() {
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('ALL');
  const [sortBy, setSortBy] = useState<'timestamp' | 'score'>('timestamp');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [selected, setSelected] = useState<Signal | null>(null);

  const { signals, connected } = useDataStream();

  const filtered = useMemo(() => {
    return signals
      .filter(s => s.symbol.toUpperCase().includes(search.toUpperCase()))
      .filter(s => typeFilter === 'ALL' || s.signal_type === typeFilter)
      .sort((a, b) => {
        const mul = sortDir === 'asc' ? 1 : -1;
        if (sortBy === 'timestamp') return mul * (new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
        return mul * (a.score - b.score);
      });
  }, [signals, search, typeFilter, sortBy, sortDir]);

  const counts = useMemo(() => {
    const result: Record<string, number> = { STRONG_BUY: 0, BUY: 0, SELL: 0, STRONG_SELL: 0 };
    for (const s of signals) {
      if (result[s.signal_type] !== undefined) result[s.signal_type]++;
    }
    return result;
  }, [signals]);

  return (
    <div className="space-y-6 h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
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
              className="bg-slate-900 border border-slate-800 rounded-lg pl-10 pr-4 py-2 text-sm w-44 focus:outline-none focus:border-emerald-500/50 transition-colors"
            />
          </div>
          <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500/50">
            <option value="ALL">All Types</option>
            <option value="STRONG_BUY">Strong Buy</option>
            <option value="BUY">Buy</option>
            <option value="NEUTRAL">Neutral</option>
            <option value="SELL">Sell</option>
            <option value="STRONG_SELL">Strong Sell</option>
          </select>
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <span className={cn('w-1.5 h-1.5 rounded-full', connected ? 'bg-emerald-500' : 'bg-amber-500')} />
            {connected ? 'Live' : 'Polling'}
          </div>
        </div>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-4 gap-4">
        {(['STRONG_BUY', 'BUY', 'SELL', 'STRONG_SELL'] as const).map(type => (
          <div key={type} className={cn(
            'border rounded-xl p-4',
            type.includes('BUY') ? 'bg-emerald-500/5 border-emerald-500/20' :
            type.includes('SELL') ? 'bg-rose-500/5 border-rose-500/20' :
            'bg-slate-500/10 border-slate-500/30'
          )}>
            <div className={cn('text-xs font-bold uppercase mb-1', typeColors[type])}>
              {type.replace('_', ' ')}
            </div>
            <div className="text-2xl font-bold text-slate-100">{counts[type]}</div>
          </div>
        ))}
      </div>

      {/* Main content */}
      <div className="flex-1 flex gap-6 min-h-0">
        {/* Table */}
        <div className={cn('bg-slate-900 border border-slate-800 rounded-xl overflow-hidden', selected ? 'w-3/5' : 'w-full')}>
          <div className="overflow-auto max-h-full">
            <table className="w-full text-left">
              <thead className="bg-slate-950/50 text-slate-500 text-xs uppercase sticky top-0">
                <tr>
                  <th className="px-6 py-3 font-medium">Symbol</th>
                  <th className="px-6 py-3 font-medium">TF</th>
                  <th className="px-6 py-3 font-medium">Type</th>
                  <th className="px-6 py-3 font-medium">Bias</th>
                  <th className="px-6 py-3 font-medium cursor-pointer hover:text-slate-300 select-none"
                    onClick={() => { if (sortBy === 'score') setSortDir(d => d === 'asc' ? 'desc' : 'asc'); else { setSortBy('score'); setSortDir('desc'); } }}>
                    <span className="flex items-center gap-1">
                      Score {sortBy === 'score' && (sortDir === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />)}
                    </span>
                  </th>
                  <th className="px-6 py-3 font-medium">Confidence</th>
                  <th className="px-6 py-3 font-medium">Price</th>
                  <th className="px-6 py-3 font-medium cursor-pointer hover:text-slate-300 select-none"
                    onClick={() => { if (sortBy === 'timestamp') setSortDir(d => d === 'asc' ? 'desc' : 'asc'); else { setSortBy('timestamp'); setSortDir('desc'); } }}>
                    <span className="flex items-center gap-1">
                      Time {sortBy === 'timestamp' && (sortDir === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />)}
                    </span>
                  </th>
                  <th className="px-6 py-3 font-medium">Confluences</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {filtered.length === 0 ? (
                  <tr><td colSpan={9} className="px-6 py-12 text-center text-slate-500">
                    {signals.length === 0 ? 'Waiting for signal data...' : 'No signals match your filters.'}
                  </td></tr>
                ) : filtered.map(signal => (
                  <tr key={signal.id} onClick={() => setSelected(selected?.id === signal.id ? null : signal)}
                    className={cn('hover:bg-slate-800/50 transition-colors cursor-pointer', selected?.id === signal.id && 'bg-slate-800/80')}>
                    <td className="px-6 py-4 font-bold">{shortenSymbol(signal.symbol)}</td>
                    <td className="px-6 py-4">
                      <span className={cn('text-[10px] font-bold px-1.5 py-0.5 rounded', {
                        'bg-amber-500/20 text-amber-400': signal.timeframe === '5m',
                        'bg-cyan-500/20 text-cyan-400': signal.timeframe === '15m',
                        'bg-emerald-500/20 text-emerald-400': signal.timeframe === '1h',
                      })}>{signal.timeframe}</span>
                    </td>
                    <td className="px-6 py-4"><SignalBadge type={signal.signal_type} /></td>
                    <td className="px-6 py-4">
                      <span className={cn('text-xs font-bold', {
                        'text-emerald-400': signal.bias === 'bullish',
                        'text-rose-400': signal.bias === 'bearish',
                        'text-slate-500': signal.bias === 'neutral',
                      })}>{signal.bias.toUpperCase()}</span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-bold">{signal.score}</span>
                        <div className="w-16 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                          <div className={cn('h-full rounded-full transition-all', {
                            'bg-emerald-500': signal.score >= 60,
                            'bg-amber-500': signal.score >= 40 && signal.score < 60,
                            'bg-rose-500': signal.score < 40,
                          })} style={{ width: `${signal.score}%` }} />
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4"><span className="font-mono text-sm">{Math.round(signal.confidence * 100)}%</span></td>
                    <td className="px-6 py-4 font-mono text-sm">${signal.price.toFixed(2)}</td>
                    <td className="px-6 py-4 text-slate-500 text-xs whitespace-nowrap">{formatTimeAgo(signal.timestamp)}</td>
                    <td className="px-6 py-4">
                      <div className="flex gap-1.5">
                        <Flag active={signal.meta_data.mss} label="MSS" />
                        <Flag active={signal.meta_data.sweep} label="SWP" />
                        <Flag active={signal.meta_data.fvg} label="FVG" />
                        <Flag active={signal.meta_data.ob} label="OB" />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Detail panel */}
        {selected && (
          <div className="w-2/5 bg-slate-900 border border-slate-800 rounded-xl p-6 overflow-auto">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-bold">Signal Detail</h3>
              <button onClick={() => setSelected(null)} className="text-slate-500 hover:text-slate-300 transition-colors"><X size={20} /></button>
            </div>
            <div className="flex items-center justify-between mb-6">
              <div>
                <div className="text-2xl font-bold">{shortenSymbol(selected.symbol)}</div>
                <SignalBadge type={selected.signal_type} />
              </div>
              <div className="text-right">
                <div className="text-2xl font-bold font-mono">${selected.price.toFixed(2)}</div>
                <div className="text-xs text-slate-500">{new Date(selected.timestamp).toLocaleString()}</div>
              </div>
            </div>
            <div className="bg-slate-950 rounded-xl p-5 border border-slate-800 mb-4">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm text-slate-400">Signal Score</span>
                <span className={cn('text-3xl font-bold font-mono', {
                  'text-emerald-400': selected.score >= 60, 'text-amber-400': selected.score >= 40 && selected.score < 60, 'text-rose-400': selected.score < 40,
                })}>{selected.score}</span>
              </div>
              <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                <div className={cn('h-full rounded-full transition-all', {
                  'bg-emerald-500': selected.score >= 60, 'bg-amber-500': selected.score >= 40 && selected.score < 60, 'bg-rose-500': selected.score < 40,
                })} style={{ width: `${selected.score}%` }} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 mb-4">
              <div className="bg-slate-950 rounded-xl p-4 border border-slate-800">
                <div className="text-sm font-bold text-slate-400 mb-2">Timeframe</div>
                <span className={cn('text-xs font-bold px-2 py-1 rounded', {
                  'bg-amber-500/20 text-amber-400': selected.timeframe === '5m',
                  'bg-cyan-500/20 text-cyan-400': selected.timeframe === '15m',
                  'bg-emerald-500/20 text-emerald-400': selected.timeframe === '1h',
                })}>{selected.timeframe}</span>
              </div>
              <div className="bg-slate-950 rounded-xl p-4 border border-slate-800">
                <div className="text-sm font-bold text-slate-400 mb-2">Bias</div>
                <div className={cn('text-lg font-bold', {
                  'text-emerald-400': selected.bias === 'bullish', 'text-rose-400': selected.bias === 'bearish', 'text-slate-400': selected.bias === 'neutral',
                })}>{selected.bias === 'bullish' ? '📈' : selected.bias === 'bearish' ? '📉' : '➖'} {selected.bias.toUpperCase()}</div>
              </div>
            </div>
            <div className="mb-4">
              <h4 className="text-sm font-bold text-slate-400 mb-3 uppercase">Confluences</h4>
              <div className="grid grid-cols-2 gap-3">
                <DetailFlag active={selected.meta_data.mss} label="Market Structure Shift" />
                <DetailFlag active={selected.meta_data.sweep} label="Liquidity Sweep" />
                <DetailFlag active={selected.meta_data.fvg} label="Fair Value Gap" />
                <DetailFlag active={selected.meta_data.ob} label="Order Block" />
                <DetailFlag active={selected.meta_data.discount} label="Discount Zone" />
                <DetailFlag active={selected.meta_data.ote} label="OTE Zone" />
              </div>
            </div>
            <div className="bg-slate-950 rounded-xl p-4 border border-slate-800">
              <div className="text-sm font-bold text-slate-400 mb-2">Model Confidence</div>
              <div className="flex items-center gap-2">
                <Activity className="text-cyan-400" size={20} />
                <span className="text-2xl font-bold">{Math.round(selected.confidence * 100)}%</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Flag({ active, label }: { active: boolean; label: string }) {
  return (
    <span className={cn('text-[10px] font-bold px-1.5 py-0.5 rounded', {
      'bg-emerald-500/20 text-emerald-400': active,
      'bg-slate-800 text-slate-600': !active,
    })}>{label}</span>
  );
}

function DetailFlag({ active, label }: { active: boolean; label: string }) {
  return (
    <div className={cn('rounded-xl p-3 border', {
      'bg-emerald-500/5 border-emerald-500/20': active,
      'bg-slate-950 border-slate-800 opacity-50': !active,
    })}>
      <div className="text-xs font-medium text-slate-400 mb-1">{label}</div>
      <div className="text-lg">{active ? '✅' : '❌'}</div>
    </div>
  );
}
