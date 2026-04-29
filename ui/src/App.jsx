import { useState } from 'react';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import Models from './pages/Models';
import Chat from './pages/Chat';
import Settings from './pages/Settings';

export default function App() {
  const [page, setPage] = useState('dashboard');

  const pages = {
    dashboard: <Dashboard />,
    models: <Models />,
    chat: <Chat />,
    settings: <Settings />,
  };

  return (
    <div className="app-layout">
      <Sidebar activePage={page} onNavigate={setPage} />
      <main className="main-content">
        {pages[page] || <Dashboard />}
      </main>
    </div>
  );
}
