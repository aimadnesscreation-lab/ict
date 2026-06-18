import { useState } from 'react';
import { useDataStream } from '../hooks/useDataStream';
import { ShieldAlert, ShieldCheck, AlertTriangle, Gauge, Calculator, DollarSign, Activity } from 'lucide-react';
import { cn } from '../utils/format';

export default function RiskCenter() {
  const { risk, connected } = useDataStream();

  // Position sizing calculator
  const [calcBalance, setCalcBalance] = useState(10000);
  const [calcRiskPct, setCalcRiskPct] = useState(1);
  const [calcEntry, setCalcEntry] = useState(1.1);
  const [calcStop, setCalcStop] = useState(1.095);
  const [calcTarget, setCalcTarget] = useState(1.11);

  const riskPerUnit = Math.abs(calcEntry - calcStop);
  const riskAmount = calcBalance * (calcRiskPct / 100);
  const positionSize = riskPerUnit > 0 ? riskAmount / riskPerUnit : 0;
  const potentialProfit = positionSize * Math.abs(calcTarget - calcEntry);
  const rrRatio = riskPerUnit > 0 ? Math.abs(calcTarget - calcEntry) / riskPerUnit : 0;

  const limitPct = (current: number, max: number) => max > 0 ? Math.min((current / max) * 100, 100) : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold flex items-center gap-3">
          <ShieldAlert className="text-amber-400" size={28} />
          Risk Center
        </h2>
        <div className="flex items-center gap-1.5 text-xs text-slate-500">
          <span className={cn('w-1.5 h-1.5 rounded-full', connected ? 'bg-emerald-500' : 'bg-amber-500')} />
          {connected ? 'Live data' : 'Polling'}
        </div>
      </div>

      {/* Status cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatusCard label="Daily Loss" current={`${risk?.current_daily_loss_pct.toFixed(1)}%`} max={`${risk?.max_daily_loss_pct.toFixed(0)}%`}
          pct={risk ? limitPct(risk.current_daily_loss_pct, risk.max_daily_loss_pct) : 0} color="bg-rose-500" icon={<AlertTriangle size={20} className="text-rose-400" />} />
        <StatusCard label="Weekly Loss" current={`${risk?.current_weekly_loss_pct.toFixed(1)}%`} max={`${risk?.max_weekly_loss_pct.toFixed(0)}%`}
          pct={risk ? limitPct(risk.current_weekly_loss_pct, risk.max_weekly_loss_pct) : 0} color="bg-amber-500" icon={<AlertTriangle size={20} className="text-amber-400" />} />
        <StatusCard label="Open Positions" current={`${risk?.open_positions_count ?? 0}`} max={`${risk?.max_open_positions ?? 3}`}
          pct={risk ? limitPct(risk.open_positions_count, risk.max_open_positions) : 0} color="bg-cyan-500" icon={<Activity size={20} className="text-cyan-400" />} />
        <StatusCard label="Account Balance" current={`$${(risk?.account_balance ?? 10000).toLocaleString()}`} max="—" pct={0}
          color="bg-emerald-500" icon={<DollarSign size={20} className="text-emerald-400" />} />
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Risk limits */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h3 className="text-lg font-bold flex items-center gap-2 mb-6"><ShieldCheck className="text-emerald-400" size={22} /> Active Limits</h3>
          <div className="space-y-5">
            <LimitBar label="Risk Per Trade" value={`${risk?.max_risk_per_trade_pct.toFixed(1)}%`} desc="Maximum risk per single trade" />
            <LimitBar label="Daily Loss Limit" value={`${risk?.max_daily_loss_pct.toFixed(0)}%`} desc="Stop trading for the day" />
            <LimitBar label="Weekly Loss Limit" value={`${risk?.max_weekly_loss_pct.toFixed(0)}%`} desc="Stop trading for the week" />
            <LimitBar label="Max Open Positions" value={`${risk?.max_open_positions}`} desc="Maximum concurrent positions" />
          </div>
        </div>

        {/* System Health */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h3 className="text-lg font-bold flex items-center gap-2 mb-6"><Gauge className="text-cyan-400" size={22} /> System Health</h3>
          <div className="space-y-4">
            <HealthIndicator label="Daily Loss Usage"
              value={risk ? `${((risk.current_daily_loss_pct / risk.max_daily_loss_pct) * 100).toFixed(0)}%` : '—'}
              status={risk && (risk.current_daily_loss_pct / risk.max_daily_loss_pct) < 0.5 ? 'good' : risk && (risk.current_daily_loss_pct / risk.max_daily_loss_pct) < 0.8 ? 'warning' : 'danger'} />
            <HealthIndicator label="Position Capacity"
              value={risk ? `${((risk.open_positions_count / risk.max_open_positions) * 100).toFixed(0)}%` : '—'}
              status={risk && (risk.open_positions_count / risk.max_open_positions) < 0.5 ? 'good' : risk && (risk.open_positions_count / risk.max_open_positions) < 0.8 ? 'warning' : 'danger'} />
            <HealthIndicator label="Risk Per Trade" value={`${risk?.max_risk_per_trade_pct.toFixed(1)}%`}
              status={risk && risk.max_risk_per_trade_pct <= 1 ? 'good' : risk && risk.max_risk_per_trade_pct <= 2 ? 'warning' : 'danger'} />
            <div className="mt-6 p-4 bg-slate-950 rounded-xl border border-slate-800">
              <div className="text-xs text-slate-500 mb-1">Overall Risk Score</div>
              <div className="flex items-center gap-3">
                <div className="flex-1 h-2 bg-slate-800 rounded-full overflow-hidden">
                  <div className="h-full rounded-full bg-emerald-500"
                    style={{ width: `${risk ? Math.min((risk.current_daily_loss_pct / risk.max_daily_loss_pct) * 50, 100) : 0}%` }} />
                </div>
                <span className="text-sm font-bold text-emerald-400">LOW</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Position Sizing Calculator */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800 flex items-center gap-2">
          <Calculator className="text-purple-400" size={22} />
          <h3 className="text-lg font-bold">Position Sizing Calculator</h3>
        </div>
        <div className="p-6 grid grid-cols-1 lg:grid-cols-2 gap-8">
          <div className="space-y-5">
            <CalcField label="Account Balance ($)" value={calcBalance} onChange={setCalcBalance} min={100} step={100} />
            <CalcField label="Risk Per Trade (%)" value={calcRiskPct} onChange={setCalcRiskPct} min={0.1} max={5} step={0.1} />
            <CalcField label="Entry Price" value={calcEntry} onChange={setCalcEntry} min={0.0001} step={0.0001} />
            <CalcField label="Stop Loss" value={calcStop} onChange={setCalcStop} min={0.0001} step={0.0001} />
            <CalcField label="Take Profit" value={calcTarget} onChange={setCalcTarget} min={0.0001} step={0.0001} />
          </div>
          <div className="space-y-4">
            <div className="text-sm font-bold text-slate-400 uppercase tracking-wide mb-4">Results</div>
            <ResultRow label="Risk per Unit" value={riskPerUnit.toFixed(4)} color="text-rose-400" />
            <ResultRow label="Risk Amount" value={`$${riskAmount.toFixed(2)}`} color="text-rose-400" />
            <div className="bg-slate-950 rounded-xl p-5 border border-slate-800">
              <div className="text-sm text-slate-400 mb-1">Position Size</div>
              <div className="text-3xl font-bold font-mono text-cyan-400">{positionSize > 0 ? positionSize.toFixed(4) : '0.0000'}</div>
              <div className="text-xs text-slate-500 mt-1">units / contracts</div>
            </div>
            <ResultRow label="Potential Profit" value={`$${potentialProfit.toFixed(2)}`} color="text-emerald-400" />
            <div className="bg-slate-950 rounded-xl p-4 border border-slate-800 flex items-center justify-between">
              <span className="text-sm text-slate-400">Risk:Reward Ratio</span>
              <span className={cn('text-2xl font-bold font-mono', rrRatio >= 2 ? 'text-emerald-400' : rrRatio >= 1 ? 'text-amber-400' : 'text-rose-400')}>
                1:{rrRatio.toFixed(2)}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusCard({ label, current, max, pct, color, icon }: {
  label: string; current: string; max: string; pct: number; color: string; icon: React.ReactNode;
}) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs font-bold text-slate-500 uppercase">{label}</span>
        {icon}
      </div>
      <div className="flex items-baseline gap-1.5 mb-2">
        <span className="text-2xl font-bold">{current}</span>
        <span className="text-sm text-slate-500">/ {max}</span>
      </div>
      <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div className={cn('h-full rounded-full', color)} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
    </div>
  );
}

function LimitBar({ label, value, desc }: { label: string; value: string; desc: string }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-sm font-bold font-mono text-emerald-400">{value}</span>
      </div>
      <div className="text-xs text-slate-500">{desc}</div>
    </div>
  );
}

function HealthIndicator({ label, value, status }: { label: string; value: string; status: 'good' | 'warning' | 'danger' }) {
  const colors = { good: 'text-emerald-400 bg-emerald-500/10', warning: 'text-amber-400 bg-amber-500/10', danger: 'text-rose-400 bg-rose-500/10' };
  const labels = { good: 'Healthy', warning: 'Caution', danger: 'Critical' };
  return (
    <div className="flex items-center justify-between">
      <div><div className="text-sm font-medium">{label}</div><div className="text-xs text-slate-500">{value}</div></div>
      <span className={cn('px-2 py-0.5 rounded text-xs font-bold', colors[status])}>{labels[status]}</span>
    </div>
  );
}

function CalcField({ label, value, onChange, min, max, step }: {
  label: string; value: number; onChange: (v: number) => void; min: number; max?: number; step: number;
}) {
  return (
    <div>
      <label className="text-sm text-slate-400 mb-1.5 block">{label}</label>
      <input type="number" value={value} min={min} max={max} step={step}
        onChange={e => onChange(parseFloat(e.target.value) || 0)}
        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500/50 transition-colors" />
    </div>
  );
}

function ResultRow({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-800 last:border-0">
      <span className="text-sm text-slate-400">{label}</span>
      <span className={cn('text-sm font-bold font-mono', color)}>{value}</span>
    </div>
  );
}
