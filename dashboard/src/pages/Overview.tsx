import React from 'react';
import { TrendingUp, Activity, BarChart3, AlertTriangle } from 'lucide-react';

const Overview: React.FC = () => {
  return (
    <div className="space-y-8">
      {/* Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard 
          title="Win Rate" 
          value="68.2%" 
          trend="+2.1%" 
          icon={<TrendingUp className="text-emerald-400" size={24} />} 
        />
        <StatCard 
          title="Total Profit" 
          value="$1,452.10" 
          trend="+$124.50" 
          icon={<Activity className="text-cyan-400" size={24} />} 
        />
        <StatCard 
          title="Profit Factor" 
          value="2.14" 
          trend="+0.05" 
          icon={<BarChart3 className="text-purple-400" size={24} />} 
        />
        <StatCard 
          title="Max Drawdown" 
          value="3.4%" 
          trend="-0.2%" 
          icon={<AlertTriangle className="text-amber-400" size={24} />} 
        />
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Signal Feed (Left 2 columns) */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <div className="p-6 border-b border-slate-800 flex justify-between items-center">
            <h3 className="text-lg font-bold">Recent Signals</h3>
            <button className="text-sm text-emerald-400 hover:underline">View All</button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="bg-slate-950/50 text-slate-500 text-xs uppercase">
                <tr>
                  <th className="px-6 py-3 font-medium">Symbol</th>
                  <th className="px-6 py-3 font-medium">Type</th>
                  <th className="px-6 py-3 font-medium">Score</th>
                  <th className="px-6 py-3 font-medium">Price</th>
                  <th className="px-6 py-3 font-medium">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                <SignalRow symbol="EURUSD" type="STRONG_BUY" score={87} price="1.1042" time="2m ago" />
                <SignalRow symbol="GBPUSD" type="BUY" score={72} price="1.2654" time="15m ago" />
                <SignalRow symbol="XAUUSD" type="SELL" score={42} price="2342.10" time="1h ago" />
                <SignalRow symbol="USDJPY" type="STRONG_SELL" score={18} price="151.24" time="3h ago" />
              </tbody>
            </table>
          </div>
        </div>

        {/* System Health (Right 1 column) */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-6">
          <h3 className="text-lg font-bold">Risk Status</h3>
          <div className="space-y-4">
            <RiskMetric label="Daily Loss Limit" value="0.4%" limit="3.0%" color="bg-emerald-500" />
            <RiskMetric label="Account Exposure" value="1.5%" limit="5.0%" color="bg-cyan-500" />
            <RiskMetric label="Active Positions" value="1" limit="3" color="bg-purple-500" />
          </div>
          
          <div className="mt-8 p-4 bg-slate-950 rounded-lg border border-slate-800">
            <h4 className="text-sm font-bold text-slate-400 mb-2">News Sentiment</h4>
            <div className="flex items-center justify-between">
              <span className="text-2xl font-bold text-emerald-400">+0.62</span>
              <span className="text-xs text-slate-500 italic">"Highly Bullish"</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

const StatCard = ({ title, value, trend, icon }: any) => (
  <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl hover:border-slate-700 transition-colors">
    <div className="flex justify-between items-start mb-4">
      {icon}
      <span className={trend.startsWith('+') ? 'text-emerald-400 text-xs font-bold' : 'text-rose-400 text-xs font-bold'}>
        {trend}
      </span>
    </div>
    <div className="text-slate-500 text-sm mb-1">{title}</div>
    <div className="text-2xl font-bold">{value}</div>
  </div>
);

const SignalRow = ({ symbol, type, score, price, time }: any) => {
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
            <div className={cn("h-full rounded-full", isBuy ? 'bg-emerald-500' : 'bg-rose-500')} style={{ width: `${score}%` }} />
          </div>
        </div>
      </td>
      <td className="px-6 py-4 font-mono text-sm">{price}</td>
      <td className="px-6 py-4 text-slate-500 text-xs">{time}</td>
    </tr>
  );
};

const RiskMetric = ({ label, value, limit, color }: any) => (
  <div className="space-y-1.5">
    <div className="flex justify-between text-xs">
      <span className="text-slate-400">{label}</span>
      <span className="text-slate-200">{value} / {limit}</span>
    </div>
    <div className="w-full h-1 bg-slate-800 rounded-full overflow-hidden">
      <div className={cn("h-full rounded-full", color)} style={{ width: `${(parseFloat(value) / parseFloat(limit)) * 100}%` }} />
    </div>
  </div>
);

const cn = (...inputs: any[]) => inputs.filter(Boolean).join(' ');

export default Overview;
