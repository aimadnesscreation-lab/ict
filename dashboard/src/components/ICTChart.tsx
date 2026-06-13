import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, ISeriesApi, CandlestickData, Time } from 'lightweight-charts';

interface ICTChartProps {
  data: CandlestickData[];
  fvgs?: any[];
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

    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#10b981',
      downColor: '#f43f5e',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#f43f5e',
    });

    candlestickSeries.setData(data);

    // Overlay FVGs
    fvgs.forEach(fvg => {
      const color = fvg.type === 'BULLISH' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(244, 63, 94, 0.2)';
      // Using extra series or markers is one way, 
      // but for "Zones" often we use Price Lines or custom primitives.
      // For this MVP, we'll focus on the core chart.
    });

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
