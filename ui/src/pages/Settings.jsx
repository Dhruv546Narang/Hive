import { useState } from 'react';

export default function Settings() {
  const [secret, setSecret] = useState('hive-secret-123');
  const [modelDir, setModelDir] = useState('~/hive/models');
  const [port, setPort] = useState('8000');
  const [ollamaUrl, setOllamaUrl] = useState('http://localhost:11434');
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div>
      <div className="page-header">
        <h1>Settings</h1>
        <p>Cluster configuration — changes require a coordinator restart</p>
      </div>

      <div className="settings-section">
        <h2>Cluster</h2>
        <div className="setting-row">
          <label>Cluster Secret</label>
          <input type="password" value={secret} onChange={e => setSecret(e.target.value)} />
        </div>
        <div className="setting-row">
          <label>Coordinator Port</label>
          <input type="number" value={port} onChange={e => setPort(e.target.value)} />
        </div>
      </div>

      <div className="settings-section">
        <h2>Models</h2>
        <div className="setting-row">
          <label>Model Directory</label>
          <input type="text" value={modelDir} onChange={e => setModelDir(e.target.value)} />
        </div>
        <div className="setting-row">
          <label>Ollama URL</label>
          <input type="text" value={ollamaUrl} onChange={e => setOllamaUrl(e.target.value)} />
        </div>
      </div>

      <div className="settings-section">
        <h2>About</h2>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.8 }}>
          <div><strong>Hive</strong> v0.1.0 — Distributed Local AI Inference</div>
          <div>Engine: Ollama (single-node) · llama.cpp RPC (multi-node)</div>
          <div>Protocol: mDNS discovery · HMAC-SHA256 auth</div>
          <div style={{ marginTop: 8 }}>
            <a href="https://github.com/Dhruv546Narang" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--amber-400)', textDecoration: 'none' }}>
              github.com/Dhruv546Narang
            </a>
          </div>
        </div>
      </div>

      <button className="btn btn-primary" onClick={handleSave}>
        {saved ? '✓ Saved' : 'Save Settings'}
      </button>
    </div>
  );
}
