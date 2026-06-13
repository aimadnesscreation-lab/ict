import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';
import Overview from './pages/Overview';
import Signals from './pages/Signals';
import Charts from './pages/Charts';
import History from './pages/History';
import RiskCenter from './pages/RiskCenter';
import Settings from './pages/Settings';

const queryClient = new QueryClient();

function App() {
  const [activePage, setActivePage] = useState('Overview');

  const renderPage = () => {
    switch (activePage) {
      case 'Overview': return <Overview />;
      case 'Signals': return <Signals />;
      case 'Charts': return <Charts />;
      case 'History': return <History />;
      case 'Risk': return <RiskCenter />;
      case 'Settings': return <Settings />;
      default:
        return (
          <div className="h-full flex items-center justify-center text-slate-500">
            {activePage} module coming soon...
          </div>
        );
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
