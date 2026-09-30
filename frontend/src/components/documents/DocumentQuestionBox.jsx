import React, { useEffect, useRef, useState } from 'react';
import { SquarePen, MessageSquareText } from 'lucide-react';
import { useI18n } from '../../utils/i18n';
import { streamDocumentQuestion } from '../../api/documentApi';
import { getConversation, getLatestDocumentConversation, warmUp } from '../../api/chatApi';
import { modelLabel } from '../../utils/modelLabels';
import MessageBubble from '../MessageBubble';
import MessageInput from '../MessageInput';

let seq = 0;
const newId = () => `d${Date.now()}-${seq++}`;

function footnotes(res, t) {
  const notes = [];
  if (res.vision_pages?.length && res.page_count > 1) {
    notes.push(t('Visual analysis used page(s) {pages} of {total}. Mention "page N" in your question to look at another page.',
      { pages: res.vision_pages.join(', '), total: res.page_count }));
  }
  if (res.pages_not_covered > 0) {
    notes.push(t('{n} later page(s) were not analysed (limit per question). Ask about "pages N–M" to see them.', { n: res.pages_not_covered }));
  }
  if (res.context?.retrieval) {
    notes.push(res.context.pages?.length
      ? t('Long document: the {used} most relevant of {total} sections were used (pages {pages}).',
        { used: res.context.sections_used, total: res.context.sections_total, pages: res.context.pages.join(', ') })
      : t('Long document: the {used} most relevant of {total} sections were used.',
        { used: res.context.sections_used, total: res.context.sections_total }));
  } else if (res.context?.context_truncated) {
    notes.push(t('Answer based on the first {used} of {total} characters (model context limit).',
      { used: res.context.context_chars_used.toLocaleString(), total: res.context.document_chars.toLocaleString() }));
  }
  return notes;
}

export default function DocumentQuestionBox({
  documentId, documentName, onImageClick, initialConversationId, onConversationsChanged,
}) {
  const { t, lang } = useI18n();
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const [think, setThink] = useState(false);

  // Document questions are answered by qwen3 unless they are visual/coding: load it early.
  useEffect(() => { warmUp('qwen3'); }, [documentId]);
  const endRef = useRef(null);

  // Restore the requested (or this document's latest) Q&A conversation from the backend.
  useEffect(() => {
    let cancelled = false;
    const load = initialConversationId
      ? getConversation(initialConversationId)
      : getLatestDocumentConversation(documentId);
    load.then((conv) => {
      if (cancelled || !conv) return;
      setConversationId(conv.id);
      setMessages(conv.messages.map((m) => ({
        id: newId(), serverId: m.id, role: m.role, text: m.content, status: 'done', feedback: m.feedback || null,
        model: m.role === 'assistant' ? m.model : null,
        routing: m.role === 'assistant' ? m.routing_reason : null,
        basis: m.basis || null,
      })));
    });
    return () => { cancelled = true; };
  }, [documentId, initialConversationId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  const replace = (id, patch) => setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)));

  const ask = async ({ question, regenerate }, msgId, previous) => {
    setBusy(true);
    let acc = '';
    let timer = null;
    const flush = () => {
      timer = null;
      replace(msgId, { status: 'streaming', text: acc });
    };
    const final = await streamDocumentQuestion(documentId, { question, conversationId, regenerate, think, language: lang }, (ev) => {
      if (ev.type === 'start') {
        if (ev.conversation_id) setConversationId(ev.conversation_id);
        replace(msgId, {
          model: ev.ollama_model, routing: ev.routing?.reason, routingExplanation: ev.routing?.explanation,
          loadingModel: Boolean(ev.model_loading), loadingModelName: modelLabel(ev.ollama_model),
        });
      } else if (ev.type === 'stage') {
        replace(msgId, { loadingModel: false, stage: ev.stage, stageLabel: ev.label });
      } else if (ev.type === 'thinking') {
        replace(msgId, { loadingModel: false, thinking: true });
      } else if (ev.type === 'delta') {
        acc += ev.text;
        if (!timer) timer = setTimeout(flush, 50);
      }
    });
    clearTimeout(timer);
    setBusy(false);
    if (final.type === 'done' && final.answer) {
      if (final.conversation_id) setConversationId(final.conversation_id);
      replace(msgId, {
        status: 'done', text: final.answer, model: final.ollama_model, routing: final.routing?.reason,
        routingExplanation: final.routing?.explanation, footnotes: footnotes(final, t), regenerateError: null,
        basis: final.basis || null, serverId: final.assistant_message_id, feedback: null,
      });
      onConversationsChanged?.();
    } else if (previous) {
      replace(msgId, { ...previous, status: 'done', regenerateError: t('Regenerate failed: {error}', { error: final.error }) });
    } else {
      replace(msgId, { status: 'error', error: final.error || t('Failed to get an answer from the local AI.'), retry: question });
    }
  };

  const handleSend = (question) => {
    if (busy) return;
    const pendingId = newId();
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: 'user', text: question },
      { id: pendingId, role: 'assistant', status: 'pending', startedAt: Date.now() },
    ]);
    ask({ question }, pendingId);
  };

  const handleRetry = (msg) => {
    if (busy || !msg.retry) return;
    replace(msg.id, { status: 'pending', error: null, startedAt: Date.now() });
    ask({ question: msg.retry }, msg.id);
  };

  const handleRegenerate = (msg) => {
    if (busy || !conversationId) return;
    const previous = { ...msg };
    replace(msg.id, { status: 'pending', text: '', regenerateError: null, startedAt: Date.now() });
    ask({ regenerate: true }, msg.id, previous);
  };

  const handleNew = () => {
    if (busy) return;
    setConversationId(null);
    setMessages([]);
  };

  const lastAssistantId = [...messages].reverse().find((m) => m.role === 'assistant')?.id;

  return (
    <div className="doc-qa">
      <div className="doc-qa-scroll">
        {messages.length === 0 ? (
          <div className="doc-qa-empty">
            <MessageSquareText size={28} />
            <p>{t('Ask anything about')} <strong>{documentName}</strong></p>
            <span>{t('Answers come from the document\'s text; visual questions ("what does the drawing on page 2 show?") use the vision model.')}</span>
          </div>
        ) : (
          <div className="chat-thread is-compact">
            {messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                onImageClick={onImageClick}
                onRetry={() => handleRetry(m)}
                canRegenerate={m.role === 'assistant' && m.id === lastAssistantId}
                onRegenerate={() => handleRegenerate(m)}
              />
            ))}
            <div ref={endRef} />
          </div>
        )}
      </div>
      <div className="doc-qa-composer">
        <button
          type="button"
          className="icon-btn doc-qa-new"
          onClick={handleNew}
          disabled={busy || messages.length === 0}
          title={t('Start a new Q&A conversation for this document')}
          aria-label={t('New Q&A conversation')}
        >
          <SquarePen size={17} />
        </button>
        <MessageInput
          onSend={handleSend}
          busy={busy}
          allowAttachments={false}
          showModelPicker={false}
          think={think}
          onThinkChange={setThink}
          placeholder={t('Ask about {name}…', { name: documentName })}
          footnote={t('Answers are generated locally from this document. Verify important values against the original.')}
        />
      </div>
    </div>
  );
}
