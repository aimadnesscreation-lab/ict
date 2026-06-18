import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';
import Overview from './pages/Overview';
import Signals from './pages/Signals';
import Charts from './pages/Charts';
import TradeLog from './pages/TradeLog';
import RiskCenter from './pages/RiskCenter';
import SettingsPage from './pages/Settings';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 5_000,
    },
  },
});

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
        {renderPage()}
      </Layout>
    </QueryClientProvider>
  );
}

export default App;
