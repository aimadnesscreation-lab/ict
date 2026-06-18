import { useState, lazy, Suspense } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';

const Overview = lazy(() => import('./pages/Overview'));
const Signals = lazy(() => import('./pages/Signals'));
const Charts = lazy(() => import('./pages/Charts'));
const TradeLog = lazy(() => import('./pages/TradeLog'));
const RiskCenter = lazy(() => import('./pages/RiskCenter'));
const SettingsPage = lazy(() => import('./pages/Settings'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 5_000,
    },
  },
});

function PageFallback() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-pulse text-slate-500 text-sm">Loading...</div>
    </div>
  );
}

function App() {
  const [activePage, setActivePage] = useState('Overview');

  const renderPage = () => {
    switch (activePage) {
      case 'Overview': return <Overview />;
      case 'Signals': return <Signals />;
      case 'Charts': return <Charts />;
      case 'TradeLog': return <TradeLog />;
      case 'Risk': return <RiskCenter />;
      case 'Settings': return <SettingsPage />;
      default: return <Overview />;
    }
  };

  return (
    <QueryClientProvider client={queryClient}>
      <Layout activePage={activePage} onPageChange={setActivePage}>
        <Suspense fallback={<PageFallback />}>
          {renderPage()}
        </Suspense>
      </Layout>
    </QueryClientProvider>
  );
}

export default App;
