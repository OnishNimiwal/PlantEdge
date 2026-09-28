import React, { useEffect, useRef, useState } from 'react';
import { SquarePen, MessageSquareText } from 'lucide-react';
import { askDocument } from '../../api/documentApi';
import { getLatestDocumentConversation } from '../../api/chatApi';
import MessageBubble from '../MessageBubble';
import MessageInput from '../MessageInput';

let seq = 0;
const newId = () => `d${Date.now()}-${seq++}`;

function footnotes(res) {
  const notes = [];
  if (res.vision_pages?.length && res.page_count > 1) {
    notes.push(
      `Visual analysis used page${res.vision_pages.length > 1 ? 's' : ''} ${res.vision_pages.join(', ')} of ${res.page_count}. ` +
      'Mention "page N" in your question to look at another page.'
    );
  }
  if (res.context?.context_truncated) {
    notes.push(
      `Answer based on the first ${res.context.context_chars_used.toLocaleString()} of ` +
      `${res.context.document_chars.toLocaleString()} characters (model context limit).`
    );
  }
  return notes;
}

export default function DocumentQuestionBox({ documentId, documentName, onImageClick }) {
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const endRef = useRef(null);

  // Restore this document's latest Q&A conversation from the backend.
  useEffect(() => {
    let cancelled = false;
    getLatestDocumentConversation(documentId).then((conv) => {
      if (cancelled || !conv) return;
      setConversationId(conv.id);
      setMessages(conv.messages.map((m) => ({
        id: newId(), role: m.role, text: m.content, status: 'done',
        model: m.role === 'assistant' ? m.model : null,
        routing: m.role === 'assistant' ? m.routing_reason : null,
      })));
    });
    return () => { cancelled = true; };
  }, [documentId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  const replace = (id, patch) => setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)));

  const ask = async (question, pendingId) => {
    setBusy(true);
    const res = await askDocument(documentId, question, conversationId);
    setBusy(false);
    if (res?.conversation_id) setConversationId(res.conversation_id);
    if (res?.success && res.answer) {
      replace(pendingId, {
        status: 'done', text: res.answer, model: res.ollama_model, routing: res.routing?.reason,
        routingExplanation: res.routing?.explanation, footnotes: footnotes(res),
      });
    } else {
      replace(pendingId, { status: 'error', error: res?.error || 'Failed to get an answer from the local AI.', retry: question });
    }
  };

  const handleSend = (question) => {
    if (busy) return;
    const pendingId = newId();
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: 'user', text: question },
      { id: pendingId, role: 'assistant', status: 'pending' },
    ]);
    ask(question, pendingId);
  };

  const handleRetry = (msg) => {
    if (busy || !msg.retry) return;
    replace(msg.id, { status: 'pending', error: null });
    ask(msg.retry, msg.id);
  };

  const handleNew = () => {
    if (busy) return;
    setConversationId(null);
    setMessages([]);
  };

  return (
    <div className="doc-qa">
      <div className="doc-qa-scroll">
        {messages.length === 0 ? (
          <div className="doc-qa-empty">
            <MessageSquareText size={28} />
            <p>Ask anything about <strong>{documentName}</strong></p>
            <span>Answers come from the document's text; visual questions ("what does the drawing on page 2 show?") use the vision model.</span>
          </div>
        ) : (
          <div className="chat-thread is-compact">
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} onImageClick={onImageClick} onRetry={() => handleRetry(m)} />
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
          title="Start a new Q&A conversation for this document"
          aria-label="New Q&A conversation"
        >
          <SquarePen size={17} />
        </button>
        <MessageInput
          onSend={handleSend}
          busy={busy}
          allowAttachments={false}
          showModelPicker={false}
          placeholder={`Ask about ${documentName}…`}
          footnote="Answers are generated locally from this document. Verify important values against the original."
        />
      </div>
    </div>
  );
}
