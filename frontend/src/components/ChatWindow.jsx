import React, { useEffect, useRef, useState } from 'react';
import { Lightbulb, DraftingCompass, Code2, FileText, ShieldCheck } from 'lucide-react';
import MessageBubble from './MessageBubble';
import { useI18n } from '../utils/i18n';

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
  const { t } = useI18n();
  return (
    <div className="chat-empty">
      <div className="chat-empty-mark" aria-hidden="true">M</div>
      <h2 className="chat-empty-title">{t('MRPL Local AI')}</h2>
      <p className="chat-empty-sub">{t('Your private, on-premise AI workbench.')}</p>
      <p className="chat-empty-hint">{t('Ask questions, analyze documents, write code, or analyze images.')}</p>
      <div className="suggestion-grid">
        {SUGGESTIONS.map((s) => {
          const Icon = s.icon;
          return (
            <button type="button" key={s.id} className="suggestion" onClick={() => onSuggestion(s)}>
              <Icon size={18} className="suggestion-icon" />
              <span className="suggestion-title">{t(s.title)}</span>
              <span className="suggestion-sub">{t(s.subtitle)}</span>
            </button>
          );
        })}
      </div>
      <div className="chat-empty-trust">
        <ShieldCheck size={14} /> {t('Data stays on this network. No external AI services are used.')}
      </div>
    </div>
  );
}

export default function ChatWindow({
  messages, onSuggestion, onImageClick, onRegenerate, onRetry, onEdit, busy, loadingConversation,
}) {
  const { t } = useI18n();
  const endRef = useRef(null);
  const [announce, setAnnounce] = useState('');
  const wasBusy = useRef(false);

  // Screen readers: announce when an answer has finished (the streamed text itself is not live).
  useEffect(() => {
    if (wasBusy.current && !busy) {
      const last = messages[messages.length - 1];
      setAnnounce(last?.status === 'error' ? (last.error || '') : t('Answer ready'));
    }
    wasBusy.current = busy;
  }, [busy, messages, t]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  if (loadingConversation) {
    return <div className="chat-scroll"><div className="chat-loading">{t('Loading conversation…')}</div></div>;
  }
  if (!messages.length) {
    return <div className="chat-scroll"><EmptyState onSuggestion={onSuggestion} /></div>;
  }

  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant');
  // Earlier answers can be regenerated once they are stored (they have a server id).
  const canRegenerate = (msg) => !msg.info && (msg === lastAssistant || Boolean(msg.serverId));
  return (
    <div className="chat-scroll">
      <div className="chat-thread">
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            onImageClick={onImageClick}
            canRegenerate={canRegenerate(msg)}
            onRegenerate={() => onRegenerate(msg)}
            onRetry={() => onRetry(msg)}
            onEdit={onEdit}
            busy={busy}
          />
        ))}
        <div ref={endRef} />
        <div className="sr-only" role="status" aria-live="polite">{announce}</div>
      </div>
    </div>
  );
}
