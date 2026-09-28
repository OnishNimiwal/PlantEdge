import React, { useEffect, useRef } from 'react';
import { Lightbulb, DraftingCompass, Code2, FileText, ShieldCheck } from 'lucide-react';
import MessageBubble from './MessageBubble';

export const SUGGESTIONS = [
  {
    id: 'explain', icon: Lightbulb, title: 'Explain a concept',
    subtitle: 'Explain federated learning and why it is useful',
    prompt: 'Explain federated learning and why it is useful for industrial companies.',
  },
  {
    id: 'drawing', icon: DraftingCompass, title: 'Analyze an engineering drawing',
    subtitle: 'Attach a drawing, P&ID or photo', prompt: 'Analyze this engineering drawing and identify the major components.',
    needsImage: true,
  },
  {
    id: 'code', icon: Code2, title: 'Write Python code',
    subtitle: 'Parse sensor logs and flag anomalies',
    prompt: 'Write a Python function that reads a CSV of sensor readings and flags values outside a given range.',
  },
  {
    id: 'document', icon: FileText, title: 'Summarize a document',
    subtitle: 'Upload a PDF, scan or text file', openDocuments: true,
  },
];

function EmptyState({ onSuggestion }) {
  return (
    <div className="chat-empty">
      <div className="chat-empty-mark" aria-hidden="true">M</div>
      <h1>MRPL Local AI</h1>
      <p className="chat-empty-sub">Your private, on-premise AI workbench.</p>
      <p className="chat-empty-hint">Ask questions, analyze documents, write code, or analyze images.</p>
      <div className="suggestion-grid">
        {SUGGESTIONS.map((s) => {
          const Icon = s.icon;
          return (
            <button type="button" key={s.id} className="suggestion" onClick={() => onSuggestion(s)}>
              <Icon size={18} className="suggestion-icon" />
              <span className="suggestion-title">{s.title}</span>
              <span className="suggestion-sub">{s.subtitle}</span>
            </button>
          );
        })}
      </div>
      <div className="chat-empty-trust">
        <ShieldCheck size={14} /> Data stays on this network. No external AI services are used.
      </div>
    </div>
  );
}

export default function ChatWindow({ messages, onSuggestion, onImageClick, onRegenerate, onRetry, loadingConversation }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  if (loadingConversation) {
    return <div className="chat-scroll"><div className="chat-loading">Loading conversation…</div></div>;
  }
  if (!messages.length) {
    return <div className="chat-scroll"><EmptyState onSuggestion={onSuggestion} /></div>;
  }

  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant');
  return (
    <div className="chat-scroll">
      <div className="chat-thread">
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            onImageClick={onImageClick}
            canRegenerate={msg === lastAssistant && !msg.info}
            onRegenerate={() => onRegenerate(msg)}
            onRetry={() => onRetry(msg)}
          />
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
