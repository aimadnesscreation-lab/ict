import { useMemo } from 'react';
import { LayoutDashboard, Radio, History, LineChart, Settings, ShieldAlert, Wifi, WifiOff, TrendingUp, TrendingDown } from 'lucide-react';
import { usePriceStream } from '../hooks/usePriceStream';
import { cn, shortenSymbol } from '../utils/format';

interface LayoutProps {
  children: React.ReactNode;
  activePage: string;
  onPageChange: (page: string) => void;
}

const NAV_ITEMS = [
  { key: 'Overview', label: 'Overview', icon: <LayoutDashboard size={20} /> },
  { key: 'Signals', label: 'Signals', icon: <Radio size={20} /> },
  { key: 'Charts', label: 'Charts', icon: <LineChart size={20} /> },
  { key: 'TradeLog', label: 'Trade Log', icon: <History size={20} /> },
  { key: 'Risk', label: 'Risk Center', icon: <ShieldAlert size={20} /> },
  { key: 'Settings', label: 'Settings', icon: <Settings size={20} /> },
];

export default function Layout({ children, activePage, onPageChange }: LayoutProps) {
  const { prices, connected } = usePriceStream();

  const tickerItems = useMemo(() => {
    return ['BTCUSDT', 'ETHUSDT'].map(symbol => {
      const tick = prices[symbol];
      if (!tick) return null;
      const isUp = tick.change_24h >= 0;
      return (
        <div key={symbol} className="flex items-center gap-1.5 px-3 py-1 rounded bg-slate-800/50 border border-slate-700/50 text-xs whitespace-nowrap">
          <span className="font-bold text-slate-300">{shortenSymbol(symbol)}</span>
          <span className="font-mono font-bold text-slate-100">
            ${tick.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          <span className={cn('flex items-center gap-0.5 font-mono text-[10px] font-bold', isUp ? 'text-emerald-400' : 'text-rose-400')}>
            {isUp ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
            {isUp ? '+' : ''}{tick.change_24h.toFixed(2)}%
          </span>
        </div>
      );
    });
  }, [prices]);

  return (
    <div className="flex min-h-screen w-full bg-slate-950 text-slate-100 font-sans">
      {/* Sidebar */}
      <aside className="w-64 border-r border-slate-800 flex flex-col shrink-0">
        <div className="p-6 border-b border-slate-800">
          <h1 className="text-xl font-bold bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent">
            ICT Intelligence
          </h1>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {NAV_ITEMS.map(item => (
            <button
              key={item.key}
              onClick={() => onPageChange(item.key)}
              className={cn(
                'flex items-center space-x-3 w-full px-3 py-2.5 rounded-lg transition-colors text-left text-sm',
                activePage === item.key
                  ? 'bg-slate-800 text-emerald-400 border border-slate-700 shadow-sm'
                  : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-100'
              )}
            >
              {item.icon}
              <span className="font-medium">{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="p-4 border-t border-slate-800 text-xs text-slate-500">
          v0.1.0 · ICT Trading Platform
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Top Header */}
        <header className="h-14 border-b border-slate-800 flex items-center gap-4 px-6 bg-slate-900/50">
          <div className="flex items-center gap-3 shrink-0">
            {connected ? (
              <Wifi size={14} className="text-emerald-400" />
            ) : (
              <WifiOff size={14} className="text-amber-400" />
            )}
            <span className={cn('text-xs font-bold', connected ? 'text-emerald-400' : 'text-amber-400')}>
              {connected ? 'LIVE' : 'MOCK'}
            </span>
            <div className="h-4 w-px bg-slate-700" />
          </div>

          <div className="flex items-center gap-2 overflow-x-auto flex-1 scrollbar-none">
            {tickerItems.some(Boolean) ? tickerItems : (
              <span className="text-xs text-slate-600 italic">Connecting to price feed...</span>
            )}
          </div>

          <div className="shrink-0 text-[10px] text-slate-600">
            {prices[Object.keys(prices)[0]]?.timestamp
              ? new Date(prices[Object.keys(prices)[0]].timestamp).toLocaleTimeString()
              : ''}
          </div>
        </header>

        {/* Page Content */}
        <div className="flex-1 overflow-auto p-6 lg:p-8">
          {children}
        </div>
      </main>
    </div>
  );
}
