import React, { useEffect, useState } from 'react';
import { Send, Bot, User, Copy, Check, Loader2, AlertCircle, SquarePen } from 'lucide-react';
import { askDocument } from '../../api/documentApi';
import { getLatestDocumentConversation } from '../../api/chatApi';

const fmtTime = (d) => new Date(d).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

export default function DocumentQuestionBox({ documentId, documentName }) {
  const [question, setQuestion] = useState('');
  const [conversation, setConversation] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [copiedIdx, setCopiedIdx] = useState(null);
  const [conversationId, setConversationId] = useState(null);

  // Restore this document's latest Q&A conversation from the backend.
  useEffect(() => {
    let cancelled = false;
    getLatestDocumentConversation(documentId).then((conv) => {
      if (cancelled || !conv) return;
      setConversationId(conv.id);
      setConversation(conv.messages.map((m) => ({
        sender: m.role === 'user' ? 'user' : 'bot',
        text: m.content,
        time: fmtTime(m.created_at),
        model: m.role === 'assistant' ? m.model : null,
        routing: m.role === 'assistant' ? m.routing_reason : null,
      })));
    });
    return () => { cancelled = true; };
  }, [documentId]);

  const handleNewConversation = () => {
    setConversationId(null);
    setConversation([]);
    setError(null);
  };

  const handleAsk = async (e) => {
    if (e) e.preventDefault();
    const q = question.trim();
    if (!q || loading) return;

    setError(null);
    const userItem = { sender: 'user', text: q, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) };
    setConversation((prev) => [...prev, userItem]);
    setQuestion('');
    setLoading(true);

    try {
      const res = await askDocument(documentId, q, conversationId);
      if (res?.conversation_id) setConversationId(res.conversation_id);
      if (res && res.success && res.answer) {
        const botItem = {
          sender: 'bot',
          text: res.answer,
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          model: res.ollama_model,
          routing: res.routing?.reason,
          context: res.context,
          visionPages: res.vision_pages,
          pageCount: res.page_count,
        };
        setConversation((prev) => [...prev, botItem]);
      } else {
        setError(res?.error || "Failed to get an answer from local AI.");
      }
    } catch (err) {
      setError(err.message || "Error communicating with AI service.");
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = (text, idx) => {
    navigator.clipboard.writeText(text);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 2000);
  };

  return (
    <div className="doc-qa-panel">
      <div className="doc-qa-messages">
        {conversation.length === 0 ? (
          <div className="qa-empty-state">
            <Bot size={32} className="qa-bot-icon" />
            <p>Ask any question about <strong>{documentName}</strong></p>
            <span>The local Qwen model on PC5 will answer based exclusively on this document.</span>
          </div>
        ) : (
          conversation.map((msg, idx) => {
            const isUser = msg.sender === 'user';
            return (
              <div key={idx} className={`qa-message-row ${isUser ? 'user' : 'bot'}`}>
                <div className={`qa-avatar ${isUser ? 'user' : 'bot'}`}>
                  {isUser ? <User size={15} /> : <Bot size={15} />}
                </div>
                <div className="qa-content-wrap">
                  {!isUser && msg.model && (
                    <span className="doc-model-tags">
                      <span className="message-model-tag">Model: {msg.model}</span>
                      {msg.routing && (
                        <span className="message-model-tag message-routing-tag">Routing: {msg.routing}</span>
                      )}
                    </span>
                  )}
                  <div className={`qa-bubble ${isUser ? 'user' : 'bot'}`}>
                    <p>{msg.text}</p>
                    {msg.visionPages?.length > 0 && msg.pageCount > 1 && (
                      <span className="context-note">
                        Visual analysis used page{msg.visionPages.length > 1 ? 's' : ''}{' '}
                        {msg.visionPages.join(', ')} of {msg.pageCount}. Mention "page N" in your question to look at another page.
                      </span>
                    )}
                    {msg.context?.context_truncated && (
                      <span className="context-note">
                        Answer based on the first {msg.context.context_chars_used.toLocaleString()} of{' '}
                        {msg.context.document_chars.toLocaleString()} characters (model context window limit).
                      </span>
                    )}
                    {!isUser && (
                      <button
                        className="qa-copy-btn"
                        onClick={() => handleCopy(msg.text, idx)}
                        title="Copy answer"
                      >
                        {copiedIdx === idx ? <Check size={12} /> : <Copy size={12} />}
                        <span>{copiedIdx === idx ? 'Copied' : 'Copy'}</span>
                      </button>
                    )}
                  </div>
                  <span className="qa-time">{msg.time}</span>
                </div>
              </div>
            );
          })
        )}

        {loading && (
          <div className="qa-message-row bot">
            <div className="qa-avatar bot">
              <Bot size={15} />
            </div>
            <div className="qa-content-wrap">
              <div className="qa-bubble bot loading">
                <Loader2 size={16} className="spin-icon" />
                <span>Analyzing document with local model...</span>
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="qa-error-alert">
            <AlertCircle size={15} />
            <span>{error}</span>
          </div>
        )}
      </div>

      <form className="qa-input-row" onSubmit={handleAsk}>
        <button
          type="button"
          className="qa-new-btn"
          onClick={handleNewConversation}
          disabled={loading || conversation.length === 0}
          title="Start a new Q&A conversation for this document"
        >
          <SquarePen size={15} />
        </button>
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={`Ask a question about ${documentName}...`}
          disabled={loading}
          className="qa-input"
        />
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="qa-send-btn"
          title="Send question"
        >
          {loading ? <Loader2 size={16} className="spin-icon" /> : <Send size={16} />}
        </button>
      </form>
    </div>
  );
}
