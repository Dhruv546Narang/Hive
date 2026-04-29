import { useEffect, useState } from 'react';
import { fetchHealth } from '../api';

const NAV = [
  { id: 'dashboard', label: 'Dashboard', icon: '⬡' },
  { id: 'models',    label: 'Models',    icon: '◈' },
  { id: 'chat',      label: 'Chat',      icon: '◉' },
  { id: 'settings',  label: 'Settings',  icon: '⚙' },
];

export default function Sidebar({ activePage, onNavigate }) {
  const [ollamaOk, setOllamaOk] = useState(false);

  useEffect(() => {
    const check = async () => {
      try {
        const data = await fetchHealth();
        setOllamaOk(data.ollama_connected);
      } catch { setOllamaOk(false); }
    };
    check();
    const id = setInterval(check, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="hex">H</div>
        <span>Hive</span>
      </div>

      <nav className="sidebar-nav">
        {NAV.map(item => (
          <button
            key={item.id}
            className={`nav-link ${activePage === item.id ? 'active' : ''}`}
            onClick={() => onNavigate(item.id)}
          >
            <span className="icon">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="sidebar-status">
        <span className={`dot ${ollamaOk ? 'dot-green' : 'dot-red'}`}></span>
        <span style={{ color: ollamaOk ? 'var(--emerald)' : 'var(--rose)' }}>
          Ollama {ollamaOk ? 'Connected' : 'Offline'}
        </span>
      </div>
    </aside>
  );
}
