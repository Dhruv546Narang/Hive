import { useState, useEffect } from 'react';
import { fetchClusterStatus } from '../api';

function StatCard({ label, value, sub, color }) {
  return (
    <div className={`stat-card ${color}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

function Bar({ label, used, total, unit, color }) {
  const pct = total > 0 ? Math.round((used / total) * 100) : 0;
  return (
    <div className="bar-container">
      <div className="bar-label">
        <span>{label}</span>
        <span>{used.toLocaleString()} / {total.toLocaleString()} {unit} ({pct}%)</span>
      </div>
      <div className="bar-track">
        <div className={`bar-fill ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function NodeCard({ node }) {
  const gpus = node.gpus || [];
  const vramUsed = (node.vram_total_mb || 0) - (node.vram_free_mb || 0);
  return (
    <div className="card node-card">
      <div className="node-header">
        <span className="node-name">{node.hostname}</span>
        <span className={`badge badge-${node.role}`}>{node.role}</span>
      </div>
      {gpus.map((g, i) => (
        <div key={i} className="node-gpu">
          {g.name} — {g.temperature_c}°C — {g.utilization_pct}% util
        </div>
      ))}
      <Bar label="VRAM" used={vramUsed} total={node.vram_total_mb || 0} unit="MB" color="amber" />
      <Bar label="RAM" used={node.ram_used_mb || 0} total={node.ram_total_mb || 0} unit="MB" color="sky" />
    </div>
  );
}

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  const load = async () => {
    try {
      const d = await fetchClusterStatus();
      setData(d);
      setErr(null);
    } catch (e) { setErr(e.message); }
  };

  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, []);

  if (err) return (
    <div>
      <div className="page-header"><h1>Dashboard</h1><p>Cluster overview</p></div>
      <div className="card" style={{ color: 'var(--rose)' }}>
        Error connecting to coordinator: {err}
      </div>
    </div>
  );
  if (!data) return (
    <div>
      <div className="page-header"><h1>Dashboard</h1><p>Loading cluster data…</p></div>
    </div>
  );

  const c = data.cluster;
  const nodes = data.nodes || [];
  const ollamaModels = data.ollama_models || [];
  const running = data.running_models || [];

  return (
    <div>
      <div className="page-header">
        <h1>Dashboard</h1>
        <p>Real-time cluster overview — auto-refreshes every 5 s</p>
      </div>

      <div className="stat-row">
        <StatCard label="Nodes" value={c.node_count} sub="in cluster" color="amber" />
        <StatCard label="Total VRAM" value={`${(c.total_vram_mb / 1024).toFixed(1)} GB`} sub={`${c.total_vram_mb.toLocaleString()} MB`} color="amber" />
        <StatCard label="Total RAM" value={`${(c.total_ram_mb / 1024).toFixed(1)} GB`} sub={`${c.total_ram_mb.toLocaleString()} MB`} color="sky" />
        <StatCard label="Usable Memory" value={`${(c.usable_memory_mb / 1024).toFixed(1)} GB`} sub="VRAM + RAM×0.6" color="emerald" />
      </div>

      <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Nodes</h2>
      <div className="card-grid" style={{ marginBottom: 32 }}>
        {nodes.map((n, i) => <NodeCard key={i} node={n} />)}
      </div>

      {ollamaModels.length > 0 && (
        <>
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Ollama Models</h2>
          <div className="card-grid" style={{ marginBottom: 32 }}>
            {ollamaModels.map((m, i) => (
              <div key={i} className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{m.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
                    {(m.size / (1024 ** 3)).toFixed(1)} GB
                    {m.details?.parameter_size ? ` · ${m.details.parameter_size}` : ''}
                    {m.details?.quantization_level ? ` · ${m.details.quantization_level}` : ''}
                  </div>
                </div>
                <span className="badge badge-available">Ready</span>
              </div>
            ))}
          </div>
        </>
      )}

      {running.length > 0 && (
        <>
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Active Inference</h2>
          <div className="card-grid">
            {running.map((m, i) => (
              <div key={i} className="card">
                <div style={{ fontWeight: 600, fontSize: 14 }}>{m.name}</div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
                  VRAM: {(m.vram / (1024 ** 3)).toFixed(1)} GB
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
