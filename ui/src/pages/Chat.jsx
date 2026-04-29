import { useState, useEffect, useRef } from 'react';
import { sendChat, fetchClusterStatus } from '../api';

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [model, setModel] = useState('');
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    fetchClusterStatus()
      .then(d => {
        const list = (d.ollama_models || []).map(m => m.name);
        setModels(list);
        if (list.length > 0 && !model) setModel(list[0]);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || loading || !model) return;

    const userMsg = { role: 'user', content: input.trim() };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput('');
    setLoading(true);
    setError(null);

    // Add placeholder assistant message
    const assistantMsg = { role: 'assistant', content: '' };
    setMessages([...newMessages, assistantMsg]);

    try {
      const apiMessages = newMessages.map(m => ({ role: m.role, content: m.content }));
      await sendChat(model, apiMessages, (chunk) => {
        assistantMsg.content += chunk;
        setMessages(prev => [...prev.slice(0, -1), { ...assistantMsg }]);
      });
    } catch (e) {
      setError(e.message);
      // Remove empty assistant bubble on error
      if (!assistantMsg.content) {
        setMessages(newMessages);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1>Chat</h1>
        <p>Talk to your models through Hive's inference pipeline</p>
      </div>

      <div className="chat-container">
        <div className="chat-messages">
          {messages.length === 0 && (
            <div style={{ textAlign: 'center', color: 'var(--text-muted)', marginTop: 80 }}>
              <div style={{ fontSize: 48, marginBottom: 16 }}>⬡</div>
              <div style={{ fontSize: 16, fontWeight: 500 }}>Start a conversation</div>
              <div style={{ fontSize: 13, marginTop: 6 }}>
                Select a model and type your message below
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className={`chat-bubble ${m.role}`}>
              {m.role === 'assistant' && !m.content && loading ? (
                <div className="typing-indicator">
                  <span /><span /><span />
                </div>
              ) : (
                <div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>
              )}
            </div>
          ))}

          {error && (
            <div style={{ color: 'var(--rose)', fontSize: 13, padding: '8px 0' }}>
              Error: {error}
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        <div className="chat-input-area">
          <select
            className="chat-model-select"
            value={model}
            onChange={e => setModel(e.target.value)}
          >
            {models.length === 0 && <option value="">No models</option>}
            {models.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          <textarea
            className="chat-input"
            placeholder={model ? `Message ${model}…` : 'No model available'}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            disabled={loading || !model}
          />
          <button
            className="btn btn-primary"
            onClick={handleSend}
            disabled={loading || !input.trim() || !model}
          >
            {loading ? '…' : 'Send'}
          </button>
        </div>
      </div>
    </div>
  );
}
