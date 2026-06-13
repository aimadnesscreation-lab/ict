import React, { useMemo } from 'react';
import {
  Settings as SettingsIcon, RotateCcw, Sliders,
  ShieldCheck, BarChart3, AlertTriangle, TrendingUp,
  TrendingDown, Radio, Activity, Newspaper, Gauge,
  Wifi, WifiOff,
} from 'lucide-react';
import { useSettings, DEFAULT_SETTINGS } from '../services/settingsService';
import type { SignalWeights, RiskSettings } from '../services/settingsService';
import { usePriceStream } from '../hooks/usePriceStream';
import { computeSignal, type ComputedSignal } from '../utils/signalCalculator';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const weightMeta: { key: keyof SignalWeights; label: string; desc: string; icon: React.ReactNode; color: string }[] = [
  { key: 'bias', label: 'HTF Bias', desc: 'Higher timeframe trend bias alignment', icon: <TrendingUp size={18} />, color: 'text-emerald-400' },
  { key: 'mss', label: 'Market Structure Shift', desc: 'CHoCH / MSS detection', icon: <Radio size={18} />, color: 'text-cyan-400' },
  { key: 'liquidity_sweep', label: 'Liquidity Sweep', desc: 'Liquidity grab detection', icon: <AlertTriangle size={18} />, color: 'text-amber-400' },
  { key: 'fvg', label: 'Fair Value Gap', desc: 'Imbalance / FVG detection', icon: <Activity size={18} />, color: 'text-purple-400' },
  { key: 'order_block', label: 'Order Block', desc: 'Institutional order block detection', icon: <BarChart3 size={18} />, color: 'text-rose-400' },
  { key: 'news', label: 'News Sentiment', desc: 'News-driven sentiment analysis', icon: <Newspaper size={18} />, color: 'text-sky-400' },
];

const riskMeta: { key: keyof RiskSettings; label: string; desc: string; suffix: string; min: number; max: number; step: number }[] = [
  { key: 'max_risk_per_trade_pct', label: 'Risk Per Trade', desc: 'Maximum risk per single trade', suffix: '%', min: 0.1, max: 5, step: 0.1 },
  { key: 'max_daily_loss_pct', label: 'Daily Loss Limit', desc: 'Stop trading after this daily loss', suffix: '%', min: 0.5, max: 20, step: 0.5 },
  { key: 'max_weekly_loss_pct', label: 'Weekly Loss Limit', desc: 'Stop trading after this weekly loss', suffix: '%', min: 1, max: 40, step: 0.5 },
  { key: 'max_open_positions', label: 'Max Open Positions', desc: 'Maximum concurrent positions', suffix: '', min: 1, max: 20, step: 1 },
];

// ── Signal UI helpers ──────────────────────────────────────────────────

const SIGNAL_STYLES: Record<ComputedSignal['signalType'], { label: string; badge: string; dot: string }> = {
  STRONG_BUY: { label: 'Strong Buy', badge: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25', dot: 'bg-emerald-400' },
  BUY:         { label: 'Buy',        badge: 'bg-emerald-500/10 text-emerald-400/80 border-emerald-500/20', dot: 'bg-emerald-400/70' },
  NEUTRAL:     { label: 'Neutral',    badge: 'bg-slate-500/10 text-slate-400 border-slate-500/20', dot: 'bg-slate-400' },
  SELL:        { label: 'Sell',       badge: 'bg-rose-500/10 text-rose-400/80 border-rose-500/20', dot: 'bg-rose-400/70' },
  STRONG_SELL: { label: 'Strong Sell', badge: 'bg-rose-500/15 text-rose-400 border-rose-500/25', dot: 'bg-rose-400' },
};

function formatPrice(symbol: string, price: number): string {
  const decimals = symbol.startsWith('XAU') ? 2
    : symbol.startsWith('BTC') || symbol.startsWith('ETH') ? 2
    : 4;
  return price.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

// ── Component ──────────────────────────────────────────────────────────

const Settings: React.FC = () => {
  const { settings, updateSignalWeight, updateRiskSetting, resetToDefaults } = useSettings();
  const { prices, connected } = usePriceStream();
  const totalWeight = Object.values(settings.signalWeights).reduce((a, b) => a + b, 0);
  const isDefault = JSON.stringify(settings) === JSON.stringify(DEFAULT_SETTINGS);

  // Compute signals for all available prices in real time
  const signals = useMemo(() => {
    const result: ComputedSignal[] = [];
    for (const tick of Object.values(prices)) {
      result.push(computeSignal(tick, settings.signalWeights));
    }
    return result;
  }, [prices, settings.signalWeights]);

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold flex items-center gap-3">
          <SettingsIcon className="text-slate-300" size={28} />
          Settings
        </h2>
        <button
          onClick={resetToDefaults}
          disabled={isDefault}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-bold transition-all ${
            isDefault
              ? 'bg-slate-800 text-slate-600 cursor-not-allowed'
              : 'bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20'
          }`}
        >
          <RotateCcw size={16} />
          Reset to Defaults
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ── Signal Weights ─────────────────────────────────────── */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <div className="p-6 border-b border-slate-800">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sliders className="text-emerald-400" size={22} />
                <h3 className="text-lg font-bold">Signal Weights</h3>
              </div>
              <div className="flex items-center gap-2">
                <Gauge size={16} className="text-slate-500" />
                <span className={`text-sm font-bold font-mono ${totalWeight === 100 ? 'text-emerald-400' : 'text-amber-400'}`}>
                  Total: {totalWeight}/100
                </span>
              </div>
            </div>
            <p className="text-xs text-slate-500 mt-1">
              Drag sliders to adjust weights — the Live Signals panel below updates instantly.
            </p>
          </div>

          <div className="p-6 space-y-6">
            {weightMeta.map(({ key, label, desc, icon, color }) => (
              <div key={key}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className={color}>{icon}</span>
                    <div>
                      <div className="text-sm font-medium">{label}</div>
                      <div className="text-[10px] text-slate-500">{desc}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      value={settings.signalWeights[key]}
                      onChange={e => updateSignalWeight(key, parseInt(e.target.value) || 0)}
                      min={0}
                      max={100}
                      className="w-16 bg-slate-950 border border-slate-800 rounded-lg px-2 py-1 text-sm font-mono text-right focus:outline-none focus:border-emerald-500/50"
                    />
                    <span className="text-xs text-slate-600 w-4">pts</span>
                  </div>
                </div>
                <div className="relative">
                  <input
                    type="range"
                    value={settings.signalWeights[key]}
                    onChange={e => updateSignalWeight(key, parseInt(e.target.value))}
                    min={0}
                    max={40}
                    className="w-full h-1.5 bg-slate-800 rounded-full appearance-none cursor-pointer accent-emerald-500 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-emerald-500 [&::-webkit-slider-thumb]:shadow-lg [&::-webkit-slider-thumb]:shadow-emerald-500/30 [&::-webkit-slider-thumb]:transition-transform [&::-webkit-slider-thumb]:hover:scale-125"
                  />
                  <div className="flex justify-between text-[10px] text-slate-600 mt-0.5">
                    <span>0</span>
                    <span>{DEFAULT_SETTINGS.signalWeights[key]}</span>
                    <span>40</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ── Risk Parameters ────────────────────────────────────── */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <div className="p-6 border-b border-slate-800">
            <div className="flex items-center gap-2">
              <ShieldCheck className="text-amber-400" size={22} />
              <h3 className="text-lg font-bold">Risk Parameters</h3>
            </div>
            <p className="text-xs text-slate-500 mt-1">
              Define risk limits used by the risk management module.
            </p>
          </div>

          <div className="p-6 space-y-6">
            {riskMeta.map(({ key, label, desc, suffix, min, max, step }) => (
              <div key={key}>
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <div className="text-sm font-medium">{label}</div>
                    <div className="text-[10px] text-slate-500">{desc}</div>
                  </div>
                  <div className="flex items-center gap-1">
                    <input
                      type="number"
                      value={settings.risk[key]}
                      onChange={e => updateRiskSetting(key, parseFloat(e.target.value) || 0)}
                      min={min}
                      max={max}
                      step={step}
                      className="w-20 bg-slate-950 border border-slate-800 rounded-lg px-2 py-1 text-sm font-mono text-right focus:outline-none focus:border-emerald-500/50"
                    />
                    {suffix && <span className="text-xs text-slate-600 w-3">{suffix}</span>}
                    {!suffix && <span className="text-xs text-slate-600 w-3">trds</span>}
                  </div>
                </div>
                <input
                  type="range"
                  value={settings.risk[key]}
                  onChange={e => updateRiskSetting(key, parseFloat(e.target.value))}
                  min={min}
                  max={max}
                  step={step}
                  className="w-full h-1.5 bg-slate-800 rounded-full appearance-none cursor-pointer accent-amber-500 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-amber-500 [&::-webkit-slider-thumb]:shadow-lg [&::-webkit-slider-thumb]:shadow-amber-500/30 [&::-webkit-slider-thumb]:transition-transform [&::-webkit-slider-thumb]:hover:scale-125"
                />
              </div>
            ))}

            {/* Quick preview of active limits */}
            <div className="mt-6 p-4 bg-slate-950 rounded-xl border border-slate-800">
              <h4 className="text-xs font-bold text-slate-500 uppercase mb-3">Current Limits Preview</h4>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <span className="text-slate-500">Risk / Trade: </span>
                  <span className="font-bold text-slate-200">{settings.risk.max_risk_per_trade_pct}%</span>
                </div>
                <div>
                  <span className="text-slate-500">Daily Loss: </span>
                  <span className="font-bold text-slate-200">{settings.risk.max_daily_loss_pct}%</span>
                </div>
                <div>
                  <span className="text-slate-500">Weekly Loss: </span>
                  <span className="font-bold text-slate-200">{settings.risk.max_weekly_loss_pct}%</span>
                </div>
                <div>
                  <span className="text-slate-500">Max Positions: </span>
                  <span className="font-bold text-slate-200">{settings.risk.max_open_positions}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Live Market Signals ──────────────────────────────────── */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div className="p-6 border-b border-slate-800">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <TrendingUp className="text-cyan-400" size={22} />
              <h3 className="text-lg font-bold">Live Market Signals</h3>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-500">
              {connected
                ? <><Wifi size={14} className="text-emerald-400" /> Live</>
                : <><WifiOff size={14} className="text-amber-400" /> Mock</>
              }
            </div>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Real-time signal computation using live prices and your current weight configuration.
            {!connected && ' Running in mock mode — prices are simulated.'}
          </p>
        </div>

        <div className="divide-y divide-slate-800">
          {signals.length === 0 && (
            <div className="p-10 text-center text-sm text-slate-600">
              Waiting for price data...
            </div>
          )}

          {signals.map(s => (
            <SignalRow key={s.symbol} signal={s} />
          ))}
        </div>

        <div className="px-6 py-3 bg-slate-950/30 border-t border-slate-800 flex items-center gap-4 text-[10px] text-slate-600">
          <span>Signal detection uses heuristic inference from price data</span>
          <span className="w-1 h-1 rounded-full bg-slate-700" />
          <span>Adjust weights above to see real-time impact on scores</span>
        </div>
      </div>

      {/* Bottom actions */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">Changes are saved automatically</div>
          <div className="text-xs text-slate-500 mt-0.5">
            All settings persist in browser localStorage. Refresh to see your changes take effect across the dashboard.
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span className="w-2 h-2 rounded-full bg-emerald-500" />
          Auto-save enabled
        </div>
      </div>
    </div>
  );
};

// ── Signal Row ────────────────────────────────────────────────────────

const SignalRow: React.FC<{ signal: ComputedSignal }> = ({ signal }) => {
  const { symbol, price, change_24h, score, signalType, flags } = signal;
  const styles = SIGNAL_STYLES[signalType];
  const isUp = change_24h >= 0;

  // Build flag indicators
  const flagStates: { key: string; active: boolean; color: string }[] = [
    { key: 'Bias', active: flags.bias !== 'neutral', color: flags.bias === 'bearish' ? 'text-rose-400' : 'text-emerald-400' },
    { key: 'MSS', active: flags.mss, color: 'text-cyan-400' },
    { key: 'Sweep', active: flags.sweep, color: 'text-amber-400' },
    { key: 'FVG', active: flags.fvg, color: 'text-purple-400' },
    { key: 'OB', active: flags.ob, color: 'text-rose-400' },
    { key: 'News', active: flags.news_sentiment > 0.5, color: 'text-sky-400' },
  ];

  return (
    <div className="px-6 py-4 hover:bg-slate-800/30 transition-colors">
      <div className="flex items-center justify-between mb-3">
        {/* Left: Symbol + Price */}
        <div className="flex items-center gap-3">
          <span className="w-20 font-bold text-sm text-slate-200">{symbol.replace('USDT', '')}</span>
          <span className="font-mono text-sm font-bold text-slate-100">{formatPrice(symbol, price)}</span>
          <span className={`flex items-center gap-1 text-xs font-bold ${isUp ? 'text-emerald-400' : 'text-rose-400'}`}>
            {isUp ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            {isUp ? '+' : ''}{change_24h.toFixed(2)}%
          </span>
        </div>

        {/* Right: Score bar + Signal badge */}
        <div className="flex items-center gap-4">
          {/* Score bar */}
          <div className="hidden sm:flex items-center gap-2">
            <div className="w-20 h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div
                className={cn(
                  'h-full rounded-full transition-all duration-500',
                  signalType === 'STRONG_BUY' || signalType === 'BUY' ? 'bg-emerald-500'
                    : signalType === 'STRONG_SELL' || signalType === 'SELL' ? 'bg-rose-500'
                    : 'bg-slate-500',
                )}
                style={{ width: `${Math.min(score, 100)}%` }}
              />
            </div>
            <span className="font-mono text-xs text-slate-500 w-7 text-right">{score}</span>
          </div>

          {/* Signal badge */}
          <span className={cn('text-[10px] font-bold px-2 py-0.5 rounded-full border', styles.badge)}>
            {styles.label}
          </span>
        </div>
      </div>

      {/* Flag indicators */}
      <div className="flex items-center gap-2">
        {flagStates.map(f => (
          <span
            key={f.key}
            className={cn(
              'text-[10px] font-medium px-2 py-0.5 rounded transition-all',
              f.active
                ? `${f.color} bg-slate-800/80 border border-slate-700/60`
                : 'text-slate-600 bg-slate-800/20 border border-transparent',
            )}
          >
            {f.key}
          </span>
        ))}
      </div>
    </div>
  );
};

export default Settings;
