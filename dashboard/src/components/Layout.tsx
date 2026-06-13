import React, { useMemo } from 'react';
import { LayoutDashboard, Radio, History, LineChart, Settings, ShieldAlert, Wifi, WifiOff, TrendingUp, TrendingDown } from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { usePriceStream } from '../hooks/usePriceStream';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface LayoutProps {
  children: React.ReactNode;
  activePage: string;
  onPageChange: (page: string) => void;
}

const TICKER_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY'];

const Layout: React.FC<LayoutProps> = ({ children, activePage, onPageChange }) => {
  const { prices, connected } = usePriceStream();

  const tickerItems = useMemo(() => {
    return TICKER_SYMBOLS.map(symbol => {
      const tick = prices[symbol];
      if (!tick) return null;
      const isUp = tick.change_24h >= 0;
      return (
        <div key={symbol} className="flex items-center gap-1.5 px-3 py-1 rounded bg-slate-800/50 border border-slate-700/50 text-xs whitespace-nowrap">
          <span className="font-bold text-slate-300">{symbol.replace('USDT', '')}</span>
          <span className="font-mono font-bold text-slate-100">
            {tick.price.toLocaleString(undefined, {
              minimumFractionDigits: symbol.startsWith('XAU') ? 2 : symbol.startsWith('BTC') || symbol.startsWith('ETH') ? 2 : 4,
              maximumFractionDigits: symbol.startsWith('XAU') ? 2 : symbol.startsWith('BTC') || symbol.startsWith('ETH') ? 2 : 4,
            })}
          </span>
          <span className={`flex items-center gap-0.5 font-mono text-[10px] font-bold ${isUp ? 'text-emerald-400' : 'text-rose-400'}`}>
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
      <aside className="w-64 border-r border-slate-800 flex flex-col">
        <div className="p-6 border-b border-slate-800">
          <h1 className="text-xl font-bold bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent">
            ICT Intelligence
          </h1>
        </div>
        
        <nav className="flex-1 p-4 space-y-2">
          <NavItem 
            icon={<LayoutDashboard size={20} />} 
            label="Overview" 
            active={activePage === 'Overview'} 
            onClick={() => onPageChange('Overview')} 
          />
          <NavItem 
            icon={<Radio size={20} />} 
            label="Signals" 
            active={activePage === 'Signals'} 
            onClick={() => onPageChange('Signals')} 
          />
          <NavItem 
            icon={<LineChart size={20} />} 
            label="Charts" 
            active={activePage === 'Charts'} 
            onClick={() => onPageChange('Charts')} 
          />
          <NavItem 
            icon={<History size={20} />} 
            label="Trade History" 
            active={activePage === 'History'} 
            onClick={() => onPageChange('History')} 
          />
          <NavItem 
            icon={<ShieldAlert size={20} />} 
            label="Risk Center" 
            active={activePage === 'Risk'} 
            onClick={() => onPageChange('Risk')} 
          />
          <NavItem 
            icon={<Settings size={20} />} 
            label="Settings" 
            active={activePage === 'Settings'} 
            onClick={() => onPageChange('Settings')} 
          />
        </nav>
        
        <div className="p-4 border-t border-slate-800 text-xs text-slate-500">
          v0.1.0-alpha
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col">
        {/* Header */}
        <header className="h-16 border-b border-slate-800 flex items-center justify-between px-6 bg-slate-900/50 gap-4">
          {/* Left: Connection status & bias */}
          <div className="flex items-center gap-4 shrink-0">
            <div className="flex items-center gap-2">
              {connected ? (
                <Wifi size={14} className="text-emerald-400" />
              ) : (
                <WifiOff size={14} className="text-amber-400" />
              )}
              <span className="text-xs font-medium text-slate-400">
                {connected ? 'LIVE' : 'MOCK'}
              </span>
            </div>
            <div className="h-4 w-px bg-slate-700" />
            <span className="text-xs text-slate-500">Bias: <span className="text-emerald-400 font-bold">BULLISH</span></span>
          </div>

          {/* Center: Ticker tape */}
          <div className="flex-1 flex items-center gap-2 overflow-x-auto scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-transparent">
            <div className="flex items-center gap-2">
              {tickerItems.some(Boolean) ? tickerItems : (
                <span className="text-xs text-slate-600 italic">Connecting to price feed...</span>
              )}
            </div>
          </div>

          {/* Right: Last updated */}
          <div className="shrink-0 text-[10px] text-slate-600 whitespace-nowrap">
            {prices[Object.keys(prices)[0]]?.timestamp
              ? new Date(prices[Object.keys(prices)[0]].timestamp).toLocaleTimeString()
              : ''}
          </div>
        </header>

        {/* Page Content */}
        <div className="flex-1 overflow-auto p-8">
          {children}
        </div>
      </main>
    </div>
  );
};

const NavItem = ({ icon, label, active = false, onClick }: { icon: React.ReactNode, label: string, active?: boolean, onClick?: () => void }) => (
  <button 
    onClick={onClick}
    className={cn(
      "flex items-center space-x-3 w-full px-3 py-2 rounded-md transition-colors text-left",
      active ? "bg-slate-800 text-emerald-400 border border-slate-700" : "text-slate-400 hover:bg-slate-900 hover:text-slate-100"
    )}
  >
    {icon}
    <span className="font-medium">{label}</span>
  </button>
);

export default Layout;
