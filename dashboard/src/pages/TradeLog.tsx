import { useState, useMemo } from 'react';
import { useDataStream } from '../hooks/useDataStream';
import { formatCurrency, formatPnl, formatDateTime, cn, shortenSymbol } from '../utils/format';
import { History, Wallet, TrendingUp, TrendingDown, Activity, Target, BarChart3, DollarSign } from 'lucide-react';
import type { OpenPosition } from '../types';

export default function TradeLog() {
  const [resultFilter, setResultFilter] = useState('ALL');
  const [symbolFilter, setSymbolFilter] = useState('ALL');

  const { trades, demo, connected } = useDataStream();

  const symbols = useMemo(() => [...new Set(trades.map(t => t.symbol))].sort(), [trades]);

  const filtered = useMemo(() => {
    return trades
      .filter(t => resultFilter === 'ALL' || t.result === resultFilter)
      .filter(t => symbolFilter === 'ALL' || t.symbol === symbolFilter);
  }, [trades, resultFilter, symbolFilter]);

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

  const openPositions = demo?.open_positions ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-2xl font-bold flex items-center gap-3">
          <History className="text-cyan-400" size={28} />
          Trade Log
        </h2>
        <div className="flex items-center gap-3">
          <select value={symbolFilter} onChange={e => setSymbolFilter(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500/50">
            <option value="ALL">All Symbols</option>
            {symbols.map(s => <option key={s} value={s}>{shortenSymbol(s)}</option>)}
          </select>
          <select value={resultFilter} onChange={e => setResultFilter(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500/50">
            <option value="ALL">All Results</option>
            <option value="WIN">Wins</option>
            <option value="LOSS">Losses</option>
            <option value="BREAK_EVEN">Break Even</option>
          </select>
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <span className={cn('w-1.5 h-1.5 rounded-full', connected ? 'bg-emerald-500' : 'bg-amber-500')} />
            {connected ? 'Live' : 'Polling'}
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 text-slate-500 text-xs font-bold uppercase mb-3"><Activity size={16} /> Win Rate</div>
          <div className="text-2xl font-bold">{(stats.winRate * 100).toFixed(1)}%</div>
          <div className="text-xs text-slate-500 mt-1">{stats.wins}W / {stats.losses}L</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 text-slate-500 text-xs font-bold uppercase mb-3"><DollarSign size={16} /> Total P&L</div>
          <div className={cn('text-2xl font-bold font-mono', stats.profit >= 0 ? 'text-emerald-400' : 'text-rose-400')}>{formatPnl(stats.profit)}</div>
          <div className="text-xs text-slate-500 mt-1">Balance: ${formatCurrency(demo?.balance ?? 5000)}</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 text-slate-500 text-xs font-bold uppercase mb-3"><Target size={16} /> Avg R:R</div>
          <div className="text-2xl font-bold">{stats.avgRr.toFixed(2)}</div>
          <div className="text-xs text-slate-500 mt-1">Target: 1:2.0</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 text-slate-500 text-xs font-bold uppercase mb-3"><BarChart3 size={16} /> Profit Factor</div>
          <div className="text-2xl font-bold">{stats.profitFactor.toFixed(2)}</div>
          <div className="text-xs text-slate-500 mt-1">{demo ? `${demo.total_trades} total trades` : '—'}</div>
        </div>
      </div>

      {/* Open Positions */}
      {openPositions.length > 0 && (
        <div className="bg-slate-900 border border-amber-500/30 rounded-xl overflow-hidden">
          <div className="px-6 py-4 border-b border-amber-500/20 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Wallet className="text-amber-400" size={20} />
              <h3 className="text-lg font-bold">Open Positions</h3>
            </div>
            <span className="text-xs bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5 rounded-full font-medium">{openPositions.length} active</span>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 p-6">
            {openPositions.map((pos: OpenPosition) => <OpenPositionCard key={pos.symbol} pos={pos} />)}
          </div>
        </div>
      )}

      {openPositions.length === 0 && trades.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 text-center">
          <Wallet className="mx-auto text-slate-600 mb-3" size={32} />
          <div className="text-slate-400 font-medium">No Open Positions</div>
          <div className="text-xs text-slate-600 mt-1">All positions closed. See trade history below.</div>
        </div>
      )}

      {/* Closed Trades */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
          <h3 className="text-lg font-bold flex items-center gap-2">
            <History size={20} className="text-cyan-400" />
            Closed Trades
          </h3>
          <div className="text-sm text-slate-500">{trades.length} total · {filtered.length} shown</div>
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
                <th className="px-6 py-3 font-medium">Exit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {filtered.length === 0 ? (
                <tr><td colSpan={10} className="px-6 py-12 text-center text-slate-500">
                  {trades.length === 0 ? 'No trades yet.' : 'No trades match your filters.'}
                </td></tr>
              ) : filtered.map(trade => (
                <tr key={trade.id} className="hover:bg-slate-800/50 transition-colors">
                  <td className="px-6 py-4 font-bold">{shortenSymbol(trade.symbol)}</td>
                  <td className="px-6 py-4">
                    <span className={cn('flex items-center gap-1 text-xs font-bold', trade.signal_type.includes('BUY') ? 'text-emerald-400' : 'text-rose-400')}>
                      {trade.signal_type.includes('BUY') ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                      {trade.signal_type}
                    </span>
                  </td>
                  <td className="px-6 py-4 font-mono text-sm">{trade.entry_price.toFixed(2)}</td>
                  <td className="px-6 py-4 font-mono text-sm">{trade.exit_price.toFixed(2)}</td>
                  <td className="px-6 py-4 text-xs text-slate-400 whitespace-nowrap">{formatDateTime(trade.entry_time)}</td>
                  <td className="px-6 py-4 text-xs text-slate-400 whitespace-nowrap">{formatDateTime(trade.exit_time)}</td>
                  <td className="px-6 py-4">
                    <span className={cn('font-mono text-sm font-bold', { 'text-emerald-400': trade.profit > 0, 'text-rose-400': trade.profit < 0, 'text-slate-400': trade.profit === 0 })}>{formatPnl(trade.profit)}</span>
                  </td>
                  <td className="px-6 py-4 font-mono text-sm">{trade.rr.toFixed(2)}</td>
                  <td className="px-6 py-4"><ResultBadge result={trade.result} /></td>
                  <td className="px-6 py-4"><ExitBadge reason={trade.exit_reason} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function OpenPositionCard({ pos }: { pos: OpenPosition }) {
  const isLong = pos.side === 'LONG';
  const isUp = pos.unrealized_pnl >= 0;
  const slPct = pos.entry_price > 0 ? Math.abs((pos.stop_loss - pos.entry_price) / pos.entry_price) * 100 : 0;
  const tpPct = pos.entry_price > 0 ? Math.abs((pos.take_profit - pos.entry_price) / pos.entry_price) * 100 : 0;
  return (
    <div className="bg-slate-950 rounded-xl border border-slate-800 p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg font-bold">{shortenSymbol(pos.symbol)}</span>
          <span className={cn('text-xs font-bold px-1.5 py-0.5 rounded', { 'bg-emerald-500/20 text-emerald-400': isLong, 'bg-rose-500/20 text-rose-400': !isLong })}>{pos.side}</span>
        </div>
        <div className={cn('text-right', pos.current_price > 0 ? (isUp ? 'text-emerald-400' : 'text-rose-400') : 'text-slate-500')}>
          <div className="text-lg font-bold font-mono">{pos.current_price > 0 ? formatPnl(pos.unrealized_pnl) : '—'}</div>
          <div className="text-[10px] uppercase">Unrealized P&L</div>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-4 text-sm">
        <div><div className="text-xs text-slate-500 mb-0.5">Entry</div><div className="font-mono font-bold">${pos.entry_price.toFixed(2)}</div></div>
        <div><div className="text-xs text-slate-500 mb-0.5">Current</div><div className="font-mono font-bold">{pos.current_price > 0 ? `$${pos.current_price.toFixed(2)}` : '—'}</div></div>
        <div><div className="text-xs text-slate-500 mb-0.5">Qty</div><div className="font-mono font-bold">{pos.quantity.toFixed(6)}</div></div>
        <div><div className="text-xs text-slate-500 mb-0.5">SL</div><div className="font-mono font-bold text-rose-400">${pos.stop_loss.toFixed(2)}</div><div className="text-[10px] text-slate-600">{slPct.toFixed(2)}%</div></div>
        <div><div className="text-xs text-slate-500 mb-0.5">TP</div><div className="font-mono font-bold text-emerald-400">${pos.take_profit.toFixed(2)}</div><div className="text-[10px] text-slate-600">{tpPct.toFixed(2)}%</div></div>
        <div><div className="text-xs text-slate-500 mb-0.5">Risk</div><div className="font-mono font-bold text-rose-400">${pos.risk_amount.toFixed(2)}</div></div>
      </div>
      <div className="text-[10px] text-slate-600">Opened {formatDateTime(pos.entry_time)}</div>
    </div>
  );
}

function ResultBadge({ result }: { result: string }) {
  return (
    <span className={cn('px-2.5 py-0.5 rounded-full text-xs font-bold', {
      'bg-emerald-500/10 text-emerald-400': result === 'WIN',
      'bg-rose-500/10 text-rose-400': result === 'LOSS',
      'bg-slate-500/10 text-slate-400': result === 'BREAK_EVEN',
    })}>
      {result === 'WIN' ? '✅ WIN' : result === 'LOSS' ? '❌ LOSS' : '➖ BE'}
    </span>
  );
}

function ExitBadge({ reason }: { reason: string }) {
  if (reason === 'TAKE_PROFIT') return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400">TP</span>;
  if (reason === 'STOP_LOSS') return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-400">SL</span>;
  return <span className="text-[10px] text-slate-600">—</span>;
}
