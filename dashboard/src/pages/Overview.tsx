import { useDataStream } from '../hooks/useDataStream';
import { usePriceStream } from '../hooks/usePriceStream';
import { formatCurrency, formatPnl, formatTimeAgo, cn, shortenSymbol } from '../utils/format';
import { TrendingUp, TrendingDown, Wallet, Activity, BarChart3, Target, Radio, Gauge } from 'lucide-react';
import SignalBadge from '../components/SignalBadge';
import type { Signal } from '../types';

export default function Overview() {
  const { prices } = usePriceStream();
  const { signals, demo, health, connected } = useDataStream();

  const btc = prices['BTCUSDT'];
  const eth = prices['ETHUSDT'];

  return (
    <div className="space-y-6">
      {/* Live Price Bar */}
      <div className="grid grid-cols-2 gap-4">
        <LivePriceCard tick={btc} symbol="BTCUSDT" />
        <LivePriceCard tick={eth} symbol="ETHUSDT" />
      </div>

      {/* Data Source Indicator */}
      <div className="flex items-center justify-end gap-2 text-xs text-slate-500">
        <span className={cn('w-2 h-2 rounded-full', connected ? 'bg-emerald-500' : 'bg-amber-500')} />
        {connected ? 'Live data stream' : 'Using REST polling'}
      </div>

      {/* Demo Account Status */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <div className="flex items-center gap-3 mb-5">
          <Wallet className="text-emerald-400" size={24} />
          <h2 className="text-lg font-bold">Demo Account</h2>
          <span className="text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded-full font-medium">
            Paper Trading
          </span>
          {health && (
            <span className="text-xs text-slate-500 ml-auto">
              HTF Bias: <span className={cn(
                'font-bold',
                health.htf_bias === 'bullish' ? 'text-emerald-400' :
                health.htf_bias === 'bearish' ? 'text-rose-400' : 'text-slate-400'
              )}>{health.htf_bias.toUpperCase()}</span>
            </span>
          )}
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          <Metric label="Balance" value={`$${formatCurrency(demo?.balance ?? 5000)}`} />
          <Metric
            label="Total P&L"
            value={formatPnl(demo?.total_profit ?? 0)}
            positive={(demo?.total_profit ?? 0) >= 0}
          />
          <Metric label="Total Trades" value={String(demo?.total_trades ?? 0)} />
          <Metric label="Win Rate" value={`${((demo?.win_rate ?? 0) * 100).toFixed(1)}%`} />
        </div>

        {/* Progress metrics */}
        {demo && demo.total_trades > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5 pt-5 border-t border-slate-800">
            <MiniStat icon={<Activity className="text-cyan-400" size={16} />} label="Profit Factor" value={(demo.profit_factor ?? 0).toFixed(2)} />
            <MiniStat icon={<BarChart3 className="text-purple-400" size={16} />} label="Max Drawdown" value={`${((demo.max_drawdown ?? 0) * 100).toFixed(1)}%`} />
            <MiniStat icon={<Target className="text-amber-400" size={16} />} label="Avg R:R" value={(demo.avg_rr ?? 0).toFixed(2)} />
            <MiniStat icon={<Gauge className="text-rose-400" size={16} />} label="Drawdown" value={`${(demo.current_drawdown_pct ?? 0).toFixed(1)}%`} />
          </div>
        )}
      </div>

      {/* System Health + Signals */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Signals */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Radio className="text-emerald-400" size={20} />
              <h3 className="text-lg font-bold">Recent Signals</h3>
            </div>
            {health && (
              <span className="text-xs text-slate-500">
                {health.total_signals_generated} generated · {health.total_signals_kept} kept
              </span>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="bg-slate-950/50 text-slate-500 text-xs uppercase">
                <tr>
                  <th className="px-6 py-3 font-medium">Symbol</th>
                  <th className="px-6 py-3 font-medium">Type</th>
                  <th className="px-6 py-3 font-medium">Score</th>
                  <th className="px-6 py-3 font-medium">Bias</th>
                  <th className="px-6 py-3 font-medium">Confluences</th>
                  <th className="px-6 py-3 font-medium">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {signals.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-6 py-10 text-center text-slate-500 text-sm">
                      Waiting for signal data...
                    </td>
                  </tr>
                )}
                {signals.slice(0, 5).map((s: Signal) => (
                  <tr key={s.id} className="hover:bg-slate-800/50 transition-colors">
                    <td className="px-6 py-4 font-bold">{shortenSymbol(s.symbol)}</td>
                    <td className="px-6 py-4"><SignalBadge type={s.signal_type} /></td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-bold">{s.score}</span>
                        <div className="w-16 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                          <div className={cn('h-full rounded-full transition-all', s.score >= 60 ? 'bg-emerald-500' : s.score >= 40 ? 'bg-amber-500' : 'bg-rose-500')} style={{ width: `${s.score}%` }} />
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className={cn('text-xs font-bold', s.bias === 'bullish' ? 'text-emerald-400' : s.bias === 'bearish' ? 'text-rose-400' : 'text-slate-500')}>
                        {s.bias.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex gap-1">
                        {s.meta_data.mss && <ConfluenceDot label="MSS" color="bg-cyan-400" />}
                        {s.meta_data.sweep && <ConfluenceDot label="SWP" color="bg-amber-400" />}
                        {s.meta_data.fvg && <ConfluenceDot label="FVG" color="bg-purple-400" />}
                        {s.meta_data.ob && <ConfluenceDot label="OB" color="bg-rose-400" />}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-slate-500 text-xs whitespace-nowrap">{formatTimeAgo(s.timestamp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* System Health */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-5">
          <h3 className="text-lg font-bold flex items-center gap-2">
            <Activity className="text-cyan-400" size={20} />
            System Health
          </h3>
          {health ? (
            <>
              <HealthRow label="Status" value={health.status} />
              <HealthRow label="Cycle Count" value={String(health.cycle_count)} />
              <HealthRow label="HTF Bias" value={health.htf_bias.toUpperCase()} />
              <HealthRow label="Signals" value={`${health.total_signals_generated} gen / ${health.total_signals_kept} kept`} />
              <HealthRow label="Trades Executed" value={String(health.total_trades_executed)} />
              <HealthRow label="Data Source" value={health.data_sources.join(', ')} />
              {health.uptime && <HealthRow label="Uptime" value={health.uptime} />}
              {health.last_error_message && (
                <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-lg">
                  <div className="text-xs text-rose-400 font-bold mb-1">Last Error</div>
                  <div className="text-xs text-rose-300">{health.last_error_message}</div>
                </div>
              )}
            </>
          ) : (
            <div className="text-sm text-slate-500">Connecting to API...</div>
          )}
        </div>
      </div>
    </div>
  );
}

function LivePriceCard({ tick, symbol }: { tick: { price: number; change_24h: number } | undefined; symbol: string }) {
  const isUp = (tick?.change_24h ?? 0) >= 0;
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-lg font-bold">{shortenSymbol(symbol)}</span>
        {tick ? (
          <span className={cn('flex items-center gap-1 text-sm font-bold', isUp ? 'text-emerald-400' : 'text-rose-400')}>
            {isUp ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
            {isUp ? '+' : ''}{tick.change_24h.toFixed(2)}%
          </span>
        ) : (
          <span className="text-xs text-slate-600">Loading...</span>
        )}
      </div>
      <div className="text-3xl font-bold font-mono">{tick ? `$${formatCurrency(tick.price)}` : '—'}</div>
    </div>
  );
}

function Metric({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  return (
    <div>
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={cn('text-2xl font-bold font-mono', positive !== undefined && (positive ? 'text-emerald-400' : 'text-rose-400'))}>{value}</div>
    </div>
  );
}

function MiniStat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2">
      {icon}
      <div>
        <div className="text-[10px] text-slate-500">{label}</div>
        <div className="text-sm font-bold">{value}</div>
      </div>
    </div>
  );
}

function HealthRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-slate-400">{label}</span>
      <span className="font-bold">{value}</span>
    </div>
  );
}

function ConfluenceDot({ label, color }: { label: string; color: string }) {
  return (
    <span className="flex items-center gap-1 text-[10px] font-medium text-slate-500">
      <span className={cn('w-1.5 h-1.5 rounded-full', color)} />
      {label}
    </span>
  );
}
