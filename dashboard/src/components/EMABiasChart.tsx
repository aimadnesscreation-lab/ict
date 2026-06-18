import { useEffect, useRef, useMemo } from 'react';
import { createChart, ColorType, LineSeries } from 'lightweight-charts';
import { cn } from '../utils/format';

interface EMABiasChartProps {
  data: { time: any; close: number }[];
}

function computeEMA(prices: number[], period: number): (number | null)[] {
  const k = 2 / (period + 1);
  const result: (number | null)[] = new Array(prices.length).fill(null);
  if (prices.length < period) return result;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += prices[i];
  result[period - 1] = sum / period;
  for (let i = period; i < prices.length; i++) {
    result[i] = prices[i] * k + result[i - 1]! * (1 - k);
  }
  return result;
}

export default function EMABiasChart({ data }: EMABiasChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const { ema12Values, ema26Values, bias, spread } = useMemo(() => {
    const prices = data.map(d => d.close);
    const e12 = computeEMA(prices, 12);
    const e26 = computeEMA(prices, 26);
    const last12 = [...e12].reverse().find(v => v !== null);
    const last26 = [...e26].reverse().find(v => v !== null);
    const lastPrice = prices[prices.length - 1];
    let bias: 'bullish' | 'bearish' | 'neutral' = 'neutral';
    let spread = 0;
    if (last12 != null && last26 != null && lastPrice > 0) {
      spread = ((last12 - last26) / lastPrice) * 100;
      if (spread > 0.5) bias = 'bullish';
      else if (spread < -0.5) bias = 'bearish';
      else bias = 'neutral';
    }
    return { ema12Values: e12, ema26Values: e26, bias, spread };
  }, [data]);

  const ema12Data = useMemo(() => {
    const result: { time: any; value: number }[] = [];
    for (let i = 0; i < data.length; i++) {
      if (ema12Values[i] !== null) result.push({ time: data[i].time, value: ema12Values[i]! });
    }
    return result;
  }, [data, ema12Values]);

  const ema26Data = useMemo(() => {
    const result: { time: any; value: number }[] = [];
    for (let i = 0; i < data.length; i++) {
      if (ema26Values[i] !== null) result.push({ time: data[i].time, value: ema26Values[i]! });
    }
    return result;
  }, [data, ema26Values]);

  useEffect(() => {
    if (!containerRef.current || ema12Data.length === 0) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0f172a' },
        textColor: '#94a3b8',
      },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      width: containerRef.current.clientWidth,
      height: 300,
      rightPriceScale: { scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });

    chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 2, title: 'EMA12', lastValueVisible: true })
      .setData(ema12Data);
    chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 2, title: 'EMA26', lastValueVisible: true })
      .setData(ema26Data);
    chart.timeScale().fitContent();

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [ema12Data, ema26Data]);

  const biasColor = bias === 'bullish' ? 'text-emerald-400' : bias === 'bearish' ? 'text-rose-400' : 'text-slate-400';
  const biasBg = bias === 'bullish' ? 'bg-emerald-500/10 border-emerald-500/30' : bias === 'bearish' ? 'bg-rose-500/10 border-rose-500/30' : 'bg-slate-800 border-slate-700/50';
  const lastEma12 = ema12Data[ema12Data.length - 1]?.value ?? null;
  const lastEma26 = ema26Data[ema26Data.length - 1]?.value ?? null;
  const lastPrice = data[data.length - 1]?.close ?? null;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-bold">EMA Bias</h3>
          <span className={cn('text-[11px] font-bold px-2.5 py-0.5 rounded-full border', biasBg, biasColor)}>
            {bias.toUpperCase()}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-0.5 rounded bg-blue-500" />
            <span className="text-slate-400">EMA12</span>
            <span className="font-mono text-slate-200 font-medium">{lastEma12?.toFixed(2) ?? '—'}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-0.5 rounded bg-amber-400" />
            <span className="text-slate-400">EMA26</span>
            <span className="font-mono text-slate-200 font-medium">{lastEma26?.toFixed(2) ?? '—'}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">Spread</span>
            <span className={cn('font-mono font-bold', biasColor)}>{spread > 0 ? '+' : ''}{spread.toFixed(2)}%</span>
          </div>
        </div>
      </div>
      <div ref={containerRef} className="w-full rounded-lg overflow-hidden border border-slate-800/50" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-4">
        <StatBox label="Price" value={lastPrice?.toFixed(2) ?? '—'} />
        <StatBox label="EMA12" value={lastEma12?.toFixed(2) ?? '—'} color="text-blue-400" />
        <StatBox label="EMA26" value={lastEma26?.toFixed(2) ?? '—'} color="text-amber-400" />
        <StatBox label="Signal" value={bias === 'bullish' ? '↑ BUY' : bias === 'bearish' ? '↓ SELL' : '— HOLD'} color={biasColor} />
      </div>
    </div>
  );
}

function StatBox({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/50">
      <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">{label}</div>
      <div className={cn('font-mono text-sm font-bold', color ?? 'text-slate-200')}>{value}</div>
    </div>
  );
}
