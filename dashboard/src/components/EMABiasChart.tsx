import React, { useEffect, useRef, useMemo } from 'react';
import { createChart, ColorType, LineSeries } from 'lightweight-charts';

interface EMABiasChartProps {
  data: { time: number; close: number }[];
}

function computeEMA(prices: number[], period: number): (number | null)[] {
  const k = 2 / (period + 1);
  const result: (number | null)[] = new Array(prices.length).fill(null);
  if (prices.length < period) return result;

  // SMA seed
  let sum = 0;
  for (let i = 0; i < period; i++) sum += prices[i];
  result[period - 1] = sum / period;

  // Recursive EMA
  for (let i = period; i < prices.length; i++) {
    result[i] = prices[i] * k + result[i - 1]! * (1 - k);
  }
  return result;
}

const EMABiasChart: React.FC<EMABiasChartProps> = ({ data }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  const { ema12, ema26, bias, spread } = useMemo(() => {
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

    return { ema12: e12, ema26: e26, bias, spread };
  }, [data]);

  const ema12Data = useMemo(() => {
    const result: { time: number; value: number }[] = [];
    for (let i = 0; i < data.length; i++) {
      if (ema12[i] !== null) result.push({ time: data[i].time as any, value: ema12[i]! });
    }
    return result;
  }, [data, ema12]);

  const ema26Data = useMemo(() => {
    const result: { time: number; value: number }[] = [];
    for (let i = 0; i < data.length; i++) {
      if (ema26[i] !== null) result.push({ time: data[i].time as any, value: ema26[i]! });
    }
    return result;
  }, [data, ema26]);

  useEffect(() => {
    if (!containerRef.current || ema12Data.length === 0) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#020617' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      width: containerRef.current.clientWidth,
      height: 300,
      rightPriceScale: {
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        mode: 0,
      },
    });

    const ema12Series = chart.addSeries(LineSeries, {
      color: '#3b82f6',
      lineWidth: 2,
      title: 'EMA12',
      lastValueVisible: true,
      priceFormat: { type: 'price', minMove: 0.01 },
    });
    ema12Series.setData(ema12Data as any);

    const ema26Series = chart.addSeries(LineSeries, {
      color: '#f59e0b',
      lineWidth: 2,
      title: 'EMA26',
      lastValueVisible: true,
      priceFormat: { type: 'price', minMove: 0.01 },
    });
    ema26Series.setData(ema26Data as any);

    // Fit the chart to show all data
    chart.timeScale().fitContent();

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [ema12Data, ema26Data]);

  const biasColor = bias === 'bullish' ? 'text-emerald-400' : bias === 'bearish' ? 'text-rose-400' : 'text-slate-400';
  const biasBg = bias === 'bullish' ? 'bg-emerald-500/10 border-emerald-500/30' : bias === 'bearish' ? 'bg-rose-500/10 border-rose-500/30' : 'bg-slate-800 border-slate-700/50';
  const biasLabel = bias === 'bullish' ? 'BULLISH' : bias === 'bearish' ? 'BEARISH' : 'NEUTRAL';
  const lastEma12 = ema12Data.length > 0 ? ema12Data[ema12Data.length - 1].value : null;
  const lastEma26 = ema26Data.length > 0 ? ema26Data[ema26Data.length - 1].value : null;
  const lastPrice = data.length > 0 ? data[data.length - 1].close : null;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-bold">EMA Bias</h3>
          <span className={`text-[11px] font-bold px-2.5 py-0.5 rounded-full border ${biasBg} ${biasColor}`}>
            {biasLabel}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-0.5 rounded bg-blue-500" />
            <span className="text-slate-400">EMA12</span>
            <span className="font-mono text-slate-200 font-medium">
              {lastEma12 !== null ? lastEma12.toFixed(2) : '—'}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-0.5 rounded bg-amber-400" />
            <span className="text-slate-400">EMA26</span>
            <span className="font-mono text-slate-200 font-medium">
              {lastEma26 !== null ? lastEma26.toFixed(2) : '—'}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">Spread</span>
            <span className={`font-mono font-bold ${biasColor}`}>
              {spread > 0 ? '+' : ''}{spread.toFixed(2)}%
            </span>
          </div>
        </div>
      </div>

      {/* Chart */}
      <div ref={containerRef} className="w-full rounded-lg overflow-hidden border border-slate-800/50" />

      {/* Footer stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-4">
        <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/50">
          <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Price</div>
          <div className="font-mono text-sm font-bold text-slate-200">
            {lastPrice !== null ? lastPrice.toFixed(2) : '—'}
          </div>
        </div>
        <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/50">
          <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">EMA12</div>
          <div className="font-mono text-sm font-bold text-blue-400">
            {lastEma12 !== null ? lastEma12.toFixed(2) : '—'}
          </div>
        </div>
        <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/50">
          <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">EMA26</div>
          <div className="font-mono text-sm font-bold text-amber-400">
            {lastEma26 !== null ? lastEma26.toFixed(2) : '—'}
          </div>
        </div>
        <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/50">
          <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Signals</div>
          <div className={`font-mono text-sm font-bold ${biasColor}`}>
            {bias === 'bullish' ? '↑ BUY' : bias === 'bearish' ? '↓ SELL' : '— HOLD'}
          </div>
        </div>
      </div>
    </div>
  );
};

export default EMABiasChart;
