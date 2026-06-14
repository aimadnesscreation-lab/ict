import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  History, Activity, TrendingUp, TrendingDown,
  DollarSign, Target, BarChart3, Wallet,
  ChevronDown, ChevronUp,
} from 'lucide-react';
import { tradingApi, type OpenPosition } from '../services/api';

const TradeLog: React.FC = () => {
  const [resultFilter, setResultFilter] = useState<string>('ALL');
  const [symbolFilter, setSymbolFilter] = useState<string>('ALL');
  const [sortBy, setSortBy] = useState<'exit_time' | 'profit'>('exit_time');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const { data: demo } = useQuery({
    queryKey: ['demoAccount'],
    queryFn: () => tradingApi.getDemoAccount(),
    refetchInterval: 30_000,
  });

  const { data: trades = [], isLoading } = useQuery({
    queryKey: ['trades', 200],
    queryFn: () => tradingApi.getTrades(200),
    refetchInterval: 30_000,
  });

  const symbols = useMemo(() => [...new Set(trades.map(t => t.symbol))].sort(), [trades]);

  const filtered = trades
    .filter(t => resultFilter === 'ALL' || t.result === resultFilter)
    .filter(t => symbolFilter === 'ALL' || t.symbol === symbolFilter)
    .sort((a, b) => {
      const mul = sortDir === 'asc' ? 1 : -1;
      if (sortBy === 'exit_time') return mul * (new Date(a.exit_time).getTime() - new Date(b.exit_time).getTime());
      return mul * (a.profit - b.profit);
    });

  const toggleSort = (field: typeof sortBy) => {
    if (sortBy === field) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortBy(field); setSortDir('desc'); }
  };

  const stats = useMemo(() => {
    if (!trades.length) return { winRate: 0, profit: 0, avgRr: 0, wins: 0, losses: 0, profitFactor: 0 };
    const wins = trades.filter(t => t.result === 'WIN');
    const losses = trades.filter(t => t.result === 'LOSS');
    const grossProfits = wins.reduce((s, t) => s + t.profit, 0);
    const grossLosses = Math.abs(losses.reduce((s, t) => s + t.profit, 0));
    return {
      winRate: wins.length / trades.length,
      profit: trades.reduce((s, t) => s + t.profit, 0),
      avgRr: trades.reduce((s, t) => s + t.rr, 0) / trades.length,
      wins: wins.length,
      losses: losses.length,
      profitFactor: grossLosses > 0 ? grossProfits / grossLosses : grossProfits > 0 ? 999 : 0,
    };
  }, [trades]);

  const formatCurrency = (v: number) =>
    (v >= 0 ? '+' : '') + v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const formatTime = (ts: string) => {
    const d = new Date(ts);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  const openPositions = demo?.open_positions ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold flex items-center gap-3">
          <History className="text-cyan-400" size={28} />
          Trade Log
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

      {/* Stats bar */}
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
          <div className="text-xs text-slate-500 mt-1">Balance: ${(demo?.balance ?? 10000).toLocaleString()}</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 text-slate-500 text-xs font-bold uppercase mb-3">
            <Target size={16} /> Avg R:R
          </div>
          <div className="text-2xl font-bold">{stats.avgRr.toFixed(2)}</div>
          <div className="text-xs text-slate-500 mt-1">Target: 1:2.0</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 text-slate-500 text-xs font-bold uppercase mb-3">
            <BarChart3 size={16} /> Profit Factor
          </div>
          <div className="text-2xl font-bold">{stats.profitFactor.toFixed(2)}</div>
          <div className="text-xs text-slate-500 mt-1">
            {demo ? `${demo.total_trades} total trades` : '—'}
          </div>
        </div>
      </div>

      {/* Open Positions */}
      {openPositions.length > 0 && (
        <div className="bg-slate-900 border border-amber-500/30 rounded-xl overflow-hidden">
          <div className="p-5 border-b border-amber-500/20 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Wallet className="text-amber-400" size={20} />
              <h3 className="text-lg font-bold">Open Positions</h3>
            </div>
            <span className="text-xs bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5 rounded-full font-medium">
              {openPositions.length} active
            </span>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 p-5">
            {openPositions.map((pos: OpenPosition) => {
              const isLong = pos.side === 'LONG';
              const isUp = pos.unrealized_pnl >= 0;
              const slPct = pos.entry_price > 0 ? Math.abs((pos.stop_loss - pos.entry_price) / pos.entry_price) * 100 : 0;
              const tpPct = pos.entry_price > 0 ? Math.abs((pos.take_profit - pos.entry_price) / pos.entry_price) * 100 : 0;
              return (
                <div key={pos.symbol} className="bg-slate-950 rounded-xl border border-slate-800 p-5 space-y-4">
                  {/* Header */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-lg font-bold">{pos.symbol}</span>
                      <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                        isLong ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'
                      }`}>
                        {isLong ? 'LONG' : 'SHORT'}
                      </span>
                    </div>
                    <div className={`text-right ${pos.current_price > 0 ? (isUp ? 'text-emerald-400' : 'text-rose-400') : 'text-slate-500'}`}>
                      <div className="text-lg font-bold font-mono">
                        {pos.current_price > 0 ? `$${formatCurrency(pos.unrealized_pnl)}` : '—'}
                      </div>
                      <div className="text-[10px] uppercase tracking-wide">
                        {pos.current_price > 0 ? 'Unrealized P&L' : 'Awaiting price'}
                      </div>
                    </div>
                  </div>

                  {/* Grid */}
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <div className="text-xs text-slate-500 mb-0.5">Entry</div>
                      <div className="font-mono font-bold">{pos.entry_price.toFixed(pos.symbol.startsWith('XAU') ? 2 : pos.symbol.startsWith('BTC') || pos.symbol.startsWith('ETH') ? 2 : 4)}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500 mb-0.5">Current</div>
                      <div className="font-mono font-bold">{pos.current_price > 0 ? pos.current_price.toFixed(pos.symbol.startsWith('XAU') ? 2 : pos.symbol.startsWith('BTC') || pos.symbol.startsWith('ETH') ? 2 : 4) : '—'}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500 mb-0.5">Stop Loss</div>
                      <div className="font-mono font-bold text-rose-400">{pos.stop_loss.toFixed(pos.symbol.startsWith('XAU') ? 2 : pos.symbol.startsWith('BTC') || pos.symbol.startsWith('ETH') ? 2 : 4)}</div>
                      <div className="text-[10px] text-slate-600">{slPct.toFixed(2)}%</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500 mb-0.5">Take Profit</div>
                      <div className="font-mono font-bold text-emerald-400">{pos.take_profit.toFixed(pos.symbol.startsWith('XAU') ? 2 : pos.symbol.startsWith('BTC') || pos.symbol.startsWith('ETH') ? 2 : 4)}</div>
                      <div className="text-[10px] text-slate-600">{tpPct.toFixed(2)}%</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500 mb-0.5">Quantity</div>
                      <div className="font-mono font-bold">{pos.quantity.toFixed(6)}</div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500 mb-0.5">Risk</div>
                      <div className="font-mono font-bold text-rose-400">${pos.risk_amount.toFixed(2)}</div>
                    </div>
                  </div>

                  {/* Time opened */}
                  <div className="text-[10px] text-slate-600">
                    Opened {formatTime(pos.entry_time)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* No open positions message */}
      {openPositions.length === 0 && trades.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 text-center">
          <Wallet className="mx-auto text-slate-600 mb-3" size={32} />
          <div className="text-slate-400 font-medium">No Open Positions</div>
          <div className="text-xs text-slate-600 mt-1">All positions have been closed. Check the trade history below.</div>
        </div>
      )}

      {/* Closed Trades */}
      <div className={`bg-slate-900 border border-slate-800 rounded-xl overflow-hidden ${openPositions.length > 0 ? '' : ''}`}>
        <div className="p-5 border-b border-slate-800 flex items-center justify-between">
          <h3 className="text-lg font-bold flex items-center gap-2">
            <History size={20} className="text-cyan-400" />
            Closed Trades
          </h3>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-slate-500">{trades.length} total</span>
            <span className="text-slate-600">/</span>
            <span className="text-slate-500">{filtered.length} shown</span>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-slate-950/50 text-slate-500 text-xs uppercase">
              <tr>
                <th className="px-6 py-3 font-medium">Symbol</th>
                <th className="px-6 py-3 font-medium">Direction</th>
                <th className="px-6 py-3 font-medium">Entry Price</th>
                <th className="px-6 py-3 font-medium">Exit Price</th>
                <th className="px-6 py-3 font-medium">Entry Time</th>
                <th className="px-6 py-3 font-medium">Exit Time</th>
                <th
                  className="px-6 py-3 font-medium cursor-pointer hover:text-slate-300 select-none"
                  onClick={() => toggleSort('profit')}
                >
                  <span className="flex items-center gap-1">
                    P&L
                    {sortBy === 'profit' && (sortDir === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />)}
                  </span>
                </th>
                <th className="px-6 py-3 font-medium">R:R</th>
                <th className="px-6 py-3 font-medium">Result</th>
                <th className="px-6 py-3 font-medium">Exit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {isLoading ? (
                <tr><td colSpan={9} className="px-6 py-12 text-center text-slate-500">Loading trade history...</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={10} className="px-6 py-12 text-center text-slate-500">
                  {trades.length === 0 ? 'No trades yet. The demo account will start trading when strong signals are generated inside a kill zone.' : 'No trades match your filters.'}
                </td></tr>
              ) : filtered.map(trade => (
                <tr key={trade.id} className="hover:bg-slate-800/50 transition-colors">
                  <td className="px-6 py-4 font-bold">{trade.symbol}</td>
                  <td className="px-6 py-4">
                    <span className={`flex items-center gap-1 text-xs font-bold ${
                      trade.signal_type === 'BUY' || trade.signal_type === 'STRONG_BUY' ? 'text-emerald-400' : 'text-rose-400'
                    }`}>
                      {trade.signal_type === 'BUY' || trade.signal_type === 'STRONG_BUY' ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                      {trade.signal_type}
                    </span>
                  </td>
                  <td className="px-6 py-4 font-mono text-sm">{trade.entry_price.toFixed(4)}</td>
                  <td className="px-6 py-4 font-mono text-sm">{trade.exit_price.toFixed(4)}</td>
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
                  <td className="px-6 py-4">
                    <ExitReasonBadge reason={trade.exit_reason} />
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
            <div className="text-xl font-bold font-mono text-emerald-400">
              +${Math.max(...filtered.map(t => t.profit), 0).toFixed(2)}
            </div>
          </div>
          <div className="bg-slate-900 border border-rose-500/20 rounded-xl p-5">
            <div className="flex items-center gap-2 text-rose-400 text-xs font-bold uppercase mb-2">
              <TrendingDown size={16} /> Worst Trade
            </div>
            <div className="text-xl font-bold font-mono text-rose-400">
              ${Math.min(...filtered.map(t => t.profit), 0).toFixed(2)}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const ExitReasonBadge = ({ reason }: { reason: string }) => {
  if (reason === 'TAKE_PROFIT') return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400">TP</span>;
  if (reason === 'STOP_LOSS') return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-400">SL</span>;
  return <span className="text-[10px] text-slate-600">—</span>;
};

export default TradeLog;
