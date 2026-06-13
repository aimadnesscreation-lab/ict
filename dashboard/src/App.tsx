import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';
import Overview from './pages/Overview';
import Charts from './pages/Charts';

const queryClient = new QueryClient();

function App() {
  const [activePage, setActivePage] = useState('Overview');

  return (
    <QueryClientProvider client={queryClient}>
      <Layout activePage={activePage} onPageChange={setActivePage}>
        {activePage === 'Overview' && <Overview />}
        {activePage === 'Charts' && <Charts />}
        {activePage !== 'Overview' && activePage !== 'Charts' && (
          <div className="h-full flex items-center justify-center text-slate-500">
            {activePage} module coming soon...
          </div>
        )}
      </Layout>
    </QueryClientProvider>
  );
}

export default App;
