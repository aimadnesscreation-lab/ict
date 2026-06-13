import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts';
import type { CandlestickData } from 'lightweight-charts';

interface ICTChartProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: CandlestickData[] & Array<any>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  fvgs?: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  orderBlocks?: any[];
}

const ICTChart: React.FC<ICTChartProps> = ({ data, fvgs = [], orderBlocks = [] }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#020617' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      width: chartContainerRef.current.clientWidth,
      height: 500,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#f43f5e',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#f43f5e',
    });

    candlestickSeries.setData(data);

    // FVG overlays are ready for future implementation
    // Each FVG would be drawn as a horizontal band using a LineSeries or Rectangle primitive

    chartRef.current = chart;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [data, fvgs, orderBlocks]);

  return <div ref={chartContainerRef} className="w-full h-full rounded-xl overflow-hidden border border-slate-800" />;
};

export default ICTChart;
