const API_BASE = '';

export async function fetchClusterStatus() {
  const r = await fetch(`${API_BASE}/api/cluster/status`);
  if (!r.ok) throw new Error(`Status ${r.status}`);
  return r.json();
}

export async function fetchHealth() {
  const r = await fetch(`${API_BASE}/api/health`);
  if (!r.ok) throw new Error(`Status ${r.status}`);
  return r.json();
}

export async function fetchNodes() {
  const r = await fetch(`${API_BASE}/api/cluster/nodes`);
  if (!r.ok) throw new Error(`Status ${r.status}`);
  return r.json();
}

export async function fetchModels() {
  const r = await fetch(`${API_BASE}/api/cluster/models`);
  if (!r.ok) throw new Error(`Status ${r.status}`);
  return r.json();
}

export async function fetchWorkers() {
  const r = await fetch(`${API_BASE}/api/cluster/workers`);
  if (!r.ok) throw new Error(`Status ${r.status}`);
  return r.json();
}

export async function fetchShardPlan(model = "qwen3.5", params = "8B") {
  const r = await fetch(`${API_BASE}/api/cluster/shard-plan?model=${model}&params=${params}`);
  if (!r.ok) throw new Error(`Status ${r.status}`);
  return r.json();
}

export async function sendChat(model, messages, onChunk) {
  const r = await fetch(`${API_BASE}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, messages, stream: true, temperature: 0.7, max_tokens: 2048 }),
  });

  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || `Status ${r.status}`);
  }

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || !trimmed.startsWith('data: ')) continue;
      const data = trimmed.slice(6);
      if (data === '[DONE]') return;
      try {
        const parsed = JSON.parse(data);
        const delta = parsed.choices?.[0]?.delta?.content;
        if (delta) onChunk(delta);
      } catch { /* skip */ }
    }
  }
}

export async function sendChatNonStream(model, messages) {
  const r = await fetch(`${API_BASE}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, messages, stream: false, temperature: 0.7, max_tokens: 2048 }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || `Status ${r.status}`);
  }
  return r.json();
}
