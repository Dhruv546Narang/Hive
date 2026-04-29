import { useState, useEffect } from 'react';
import { fetchClusterStatus } from '../api';

export default function Models() {
  const [data, setData] = useState(null);

  useEffect(() => {
    fetchClusterStatus().then(setData).catch(console.error);
  }, []);

  if (!data) return (
    <div>
      <div className="page-header"><h1>Models</h1><p>Loading…</p></div>
    </div>
  );

  const ollama = data.ollama_models || [];
  const registry = data.registry_models || [];

  return (
    <div>
      <div className="page-header">
        <h1>Models</h1>
        <p>Installed models and registry — capacity based on current cluster memory</p>
      </div>

      {ollama.length > 0 && (
        <>
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Installed via Ollama</h2>
          <div className="card-grid" style={{ marginBottom: 36 }}>
            {ollama.map((m, i) => (
              <div key={i} className="card model-card">
                <div className="model-header">
                  <div>
                    <div className="model-name">{m.name}</div>
                    <div className="model-meta">
                      <span>{(m.size / (1024 ** 3)).toFixed(1)} GB</span>
                      {m.details?.parameter_size && <span>{m.details.parameter_size}</span>}
                      {m.details?.quantization_level && <span>{m.details.quantization_level}</span>}
                      {m.details?.family && <span>{m.details.family}</span>}
                    </div>
                  </div>
                  <span className="badge badge-available">✓ Ready</span>
                </div>
                {m.modified_at && (
                  <div className="model-notes">
                    Last modified: {new Date(m.modified_at).toLocaleDateString()}
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Model Registry</h2>
      <div className="card-grid">
        {registry.map((m, i) => {
          const statusClass = `badge-${m.status}`;
          const statusLabel = { available: '✓ Available', downloadable: '↓ Download', locked: '🔒 Locked' }[m.status] || m.status;
          return (
            <div key={i} className="card model-card">
              <div className="model-header">
                <div>
                  <div className="model-name">{m.name}</div>
                  <div className="model-meta">
                    <span>{m.params}</span>
                    <span>{m.vram_gb} GB VRAM</span>
                  </div>
                </div>
                <span className={`badge ${statusClass}`}>{statusLabel}</span>
              </div>
              <div className="model-notes">{m.notes}</div>
              {m.status === 'downloadable' && m.hf_url && (
                <a href={m.hf_url} target="_blank" rel="noopener noreferrer" className="btn btn-secondary" style={{ marginTop: 6, textDecoration: 'none', width: 'fit-content' }}>
                  Download from HuggingFace ↗
                </a>
              )}
              {m.status === 'locked' && (
                <div style={{ fontSize: 12, color: 'var(--rose)', marginTop: 4 }}>
                  Needs {m.vram_gb} GB — add more nodes to unlock
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
