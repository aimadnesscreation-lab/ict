import React from 'react';
import { TrendingUp, Activity, BarChart3, Wallet, Target } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { tradingApi, type Signal } from '../services/api';

interface DemoAccountData {
  balance: number;
  initial_balance: number;
  total_profit: number;
  total_trades: number;
  win_rate: number;
  profit_factor: number;
  max_drawdown: number;
  avg_rr: number;
  total_wins: number;
  total_losses: number;
  peak_balance: number;
  current_drawdown_pct: number;
}

const pricePrecision = (_symbol: string): number => 2;

const _NOW = Date.now();

const Overview: React.FC = () => {
  const { data: signals = [] } = useQuery({
    queryKey: ['signals', 5],
    queryFn: () => tradingApi.getSignals(5),
    refetchInterval: 30_000,
  });

  const { data: demo } = useQuery({
    queryKey: ['demoAccount'],
    queryFn: async () => {
      const res = await fetch('/demo/account');
      return res.json() as Promise<DemoAccountData>;
    },
    refetchInterval: 30_000,
  });

  const { data: perf } = useQuery({
    queryKey: ['performance'],
    queryFn: () => tradingApi.getPerformance(),
    refetchInterval: 30_000,
  });

  const { data: risk } = useQuery({
    queryKey: ['risk'],
    queryFn: () => tradingApi.getRiskStatus(),
    refetchInterval: 30_000,
  });

  const formatCurrency = (val: number) =>
    val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const formatTime = (ts: string) => {
    const diff = _NOW - new Date(ts).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  };

  const winRate = demo ? demo.win_rate : (perf?.win_rate ?? 0);
  const totalPnl = demo ? demo.total_profit : (perf?.total_pnl ?? 0);
  const profitFactor = demo ? demo.profit_factor : (perf?.profit_factor ?? 0);
  const maxDd = demo ? demo.max_drawdown : (perf?.max_drawdown ?? 0);
  const totalTrades = demo ? demo.total_trades : (perf?.total_trades ?? 0);
  const avgRr = demo ? demo.avg_rr : (perf?.avg_rr ?? 0);
  const accountBalance = demo?.balance ?? 10000;

  return (
    <div className="space-y-8">
      {/* Account Status Bar */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <div className="flex items-center gap-3 mb-4">
          <Wallet className="text-emerald-400" size={24} />
          <h2 className="text-lg font-bold">Demo Account</h2>
          <span className="text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded-full font-medium">
            Paper Trading
          </span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          <div>
            <div className="text-xs text-slate-500 mb-1">Balance</div>
            <div className="text-2xl font-bold font-mono">
              ${formatCurrency(accountBalance)}
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Total P&L</div>
            <div className={`text-2xl font-bold font-mono ${totalPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {totalPnl >= 0 ? '+' : ''}${formatCurrency(totalPnl)}
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Total Trades</div>
            <div className="text-2xl font-bold">{totalTrades}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Avg R:R</div>
            <div className="text-2xl font-bold">{avgRr > 0 ? avgRr.toFixed(2) : '—'}</div>
          </div>
        </div>
      </div>

      {/* Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          title="Win Rate"
          value={`${(winRate * 100).toFixed(1)}%`}
          trend={totalTrades > 0 ? `${demo?.total_wins ?? 0}W / ${demo?.total_losses ?? 0}L` : ''}
          icon={<TrendingUp className="text-emerald-400" size={24} />}
        />
        <StatCard
          title="Profit Factor"
          value={profitFactor > 0 ? profitFactor.toFixed(2) : '—'}
          trend={profitFactor >= 1.5 ? 'Healthy' : profitFactor > 0 ? 'Below 1.5' : ''}
          icon={<Activity className="text-cyan-400" size={24} />}
        />
        <StatCard
          title="Max Drawdown"
          value={`${(maxDd * 100).toFixed(1)}%`}
          trend={demo?.current_drawdown_pct ? `Current: ${demo.current_drawdown_pct.toFixed(1)}%` : ''}
          icon={<BarChart3 className="text-purple-400" size={24} />}
        />
        <StatCard
          title="Avg Risk:Reward"
          value={avgRr > 0 ? `1:${avgRr.toFixed(1)}` : '—'}
          trend={avgRr >= 2 ? 'Target met' : avgRr > 0 ? 'Below 2.0' : ''}
          icon={<Target className="text-amber-400" size={24} />}
        />
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Signals (Left 2 columns) */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <div className="p-6 border-b border-slate-800 flex justify-between items-center">
            <h3 className="text-lg font-bold">Recent Signals</h3>
            {signals.length > 0 && (
              <span className="text-xs text-slate-500">{signals.length} active</span>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="bg-slate-950/50 text-slate-500 text-xs uppercase">
                <tr>
                  <th className="px-6 py-3 font-medium">Symbol</th>
                  <th className="px-6 py-3 font-medium">Type</th>
                  <th className="px-6 py-3 font-medium">Score</th>
                  <th className="px-6 py-3 font-medium">Price</th>
                  <th className="px-6 py-3 font-medium">Kill Zone</th>
                  <th className="px-6 py-3 font-medium">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {signals.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-6 py-8 text-center text-slate-500 text-sm">
                      Waiting for signal data...
                    </td>
                  </tr>
                )}
                {signals.map((s: Signal) => (
                  <SignalRow
                    key={s.id}
                    symbol={s.symbol}
                    type={s.signal_type}
                    score={s.score}
                    price={s.price}
                    killZone={(s.meta_data as any)?.in_kill_zone ?? false}
                    time={formatTime(s.timestamp)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Account Health (Right 1 column) */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-6">
          <h3 className="text-lg font-bold">Account Health</h3>
          <div className="space-y-4">
            <RiskMetric
              label="Daily Loss Limit"
              value={risk ? `${(risk.current_daily_loss_pct).toFixed(1)}%` : '0%'}
              limit={`${risk?.max_daily_loss_pct ?? 3}%`}
              color="bg-emerald-500"
            />
            <RiskMetric
              label="Drawdown (Current)"
              value={demo ? `${demo.current_drawdown_pct.toFixed(1)}%` : '0%'}
              limit="10%"
              color="bg-amber-500"
            />
            <RiskMetric
              label="Account Exposure"
              value={risk ? `${(risk.current_daily_loss_pct).toFixed(1)}%` : '0%'}
              limit={`${risk?.max_risk_per_trade_pct ?? 1}%`}
              color="bg-cyan-500"
            />
          </div>
          
          {demo && (
            <div className="mt-6 p-4 bg-slate-950 rounded-lg border border-slate-800">
              <h4 className="text-sm font-bold text-slate-400 mb-3">Trade Summary</h4>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="text-slate-500">Wins:</div>
                <div className="text-right font-bold text-emerald-400">{demo.total_wins}</div>
                <div className="text-slate-500">Losses:</div>
                <div className="text-right font-bold text-rose-400">{demo.total_losses}</div>
                <div className="text-slate-500">Peak Balance:</div>
                <div className="text-right font-bold text-slate-200">${formatCurrency(demo.peak_balance)}</div>
                <div className="text-slate-500">Avg R:R:</div>
                <div className="text-right font-bold text-slate-200">1:{demo.avg_rr.toFixed(1)}</div>
              </div>
            </div>
          )}

          {!demo && totalTrades === 0 && (
            <div className="mt-6 p-4 bg-slate-950 rounded-lg border border-slate-800">
              <h4 className="text-sm font-bold text-slate-400 mb-2">Demo Account Inactive</h4>
              <p className="text-xs text-slate-500">
                The demo account will start trading when strong signals (score ≥ 60) are generated.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// ── Sub-components ──────────────────────────────────────────────────────

const StatCard = ({ title, value, trend, icon }: { title: string; value: string; trend?: string; icon: React.ReactNode }) => (
  <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl hover:border-slate-700 transition-colors">
    <div className="flex justify-between items-start mb-4">
      {icon}
      {trend && (
        <span className="text-emerald-400 text-xs font-bold">
          {trend}
        </span>
      )}
    </div>
    <div className="text-slate-500 text-sm mb-1">{title}</div>
    <div className="text-2xl font-bold">{value}</div>
  </div>
);

const SignalRow = ({ symbol, type, score, price, killZone, time }: {
  symbol: string; type: string; score: number; price: number; killZone: boolean; time: string;
}) => {
  const isBuy = type.includes('BUY');
  return (
    <tr className="hover:bg-slate-800/50 transition-colors cursor-pointer group">
      <td className="px-6 py-4 font-bold">{symbol}</td>
      <td className="px-6 py-4">
        <span className={isBuy ? 'text-emerald-400 font-medium' : 'text-rose-400 font-medium'}>
          {type}
        </span>
      </td>
      <td className="px-6 py-4">
        <div className="flex items-center space-x-2">
          <span className="text-sm font-mono">{score}</span>
          <div className="w-12 h-1.5 bg-slate-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${isBuy ? 'bg-emerald-500' : 'bg-rose-500'}`}
              style={{ width: `${score}%` }}
            />
          </div>
        </div>
      </td>
      <td className="px-6 py-4 font-mono text-sm">{price.toFixed(pricePrecision(symbol))}</td>
      <td className="px-6 py-4">
        {killZone ? (
          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400">
            KILL ZONE
          </span>
        ) : (
          <span className="text-[10px] text-slate-600">—</span>
        )}
      </td>
      <td className="px-6 py-4 text-slate-500 text-xs">{time}</td>
    </tr>
  );
};

const RiskMetric = ({ label, value, limit, color }: {
  label: string; value: string; limit: string; color: string;
}) => {
  const numVal = parseFloat(value);
  const numLimit = parseFloat(limit);
  const pct = numLimit > 0 ? Math.min((numVal / numLimit) * 100, 100) : 0;
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-200">{value} / {limit}</span>
      </div>
      <div className="w-full h-1 bg-slate-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
};

export default Overview;
