import React from 'react';
import { LayoutDashboard, Radio, History, LineChart, Settings, ShieldAlert } from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface LayoutProps {
  children: React.ReactNode;
  activePage: string;
  onPageChange: (page: string) => void;
}

const Layout: React.FC<LayoutProps> = ({ children, activePage, onPageChange }) => {
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
        <header className="h-16 border-b border-slate-800 flex items-center justify-between px-8 bg-slate-900/50">
          <div className="flex items-center space-x-4">
            <span className="flex items-center space-x-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-sm font-medium">System Online</span>
            </span>
            <div className="h-4 w-px bg-slate-700" />
            <span className="text-sm text-slate-400">Market Bias: <span className="text-emerald-400 font-bold">BULLISH</span></span>
          </div>
          
          <div className="flex items-center space-x-4">
            <div className="bg-slate-800 px-3 py-1 rounded text-sm border border-slate-700">
              EURUSD: 1.1042
            </div>
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
