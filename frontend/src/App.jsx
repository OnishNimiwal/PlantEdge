import React, { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import ChatWindow from './components/ChatWindow';
import MessageInput from './components/MessageInput';
import ImageLightbox from './components/ImageLightbox';
// Loaded on demand to keep the initial bundle small.
const DocumentsPage = lazy(() => import('./components/documents/DocumentsPage'));
import {
  streamMessage, fetchModels, getConversation, listConversations,
  renameConversation, deleteConversation,
} from './api/chatApi';

const CONVERSATION_KEY = 'mrpl.chat.conversationId';
const THEME_KEY = 'mrpl.theme';
const SIDEBAR_KEY = 'mrpl.sidebar.collapsed';
const MOBILE_QUERY = '(max-width: 860px)';

function readSidebarCollapsed() {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === '1';
  } catch {
    return false;
  }
}

function readTheme() {
  try {
    return localStorage.getItem(THEME_KEY) || 'system';
  } catch {
    return 'system';
  }
}

// Browser storage only remembers WHICH conversation is open; the backend holds its content.
function readStoredConversation() {
  try {
    return localStorage.getItem(CONVERSATION_KEY);
  } catch {
    return null;
  }
}

function storeConversation(id) {
  try {
    if (id) localStorage.setItem(CONVERSATION_KEY, id);
    else localStorage.removeItem(CONVERSATION_KEY);
  } catch {
    /* storage unavailable: history still lives on the server */
  }
}

let seq = 0;
const newId = () => `m${Date.now()}-${seq++}`;

function ocrFootnote(result) {
  const withLayout = (result.ocr || []).some((o) => o.complex_layout);
  return withLayout ? ['A table or multi-column layout was detected; reading order of the OCR text may be wrong.'] : [];
}

/** Server message -> UI message */
function fromServer(conv) {
  return conv.messages.map((m) => ({
    id: newId(),
    role: m.role,
    text: m.content,
    images: m.images || [],
    model: m.role === 'assistant' ? m.model : null,
    routing: m.role === 'assistant' ? m.routing_reason : null,
    info: m.role === 'assistant' && !m.model && m.routing_reason === 'vision',
    status: 'done',
  }));
}

/** API response -> assistant message */
function fromResult(result) {
  return {
    role: 'assistant',
    text: result.response,
    model: result.needs_image ? null : result.ollama_model || result.model,
    routing: result.routing?.reason,
    routingExplanation: result.routing?.explanation,
    info: Boolean(result.needs_image),
    ocr: result.ocr || null,
    footnotes: ocrFootnote(result),
    status: 'done',
  };
}

export default function App() {
  const [view, setView] = useState('chat'); // 'chat' | 'documents'
  const [sidebarOpen, setSidebarOpen] = useState(false);          // small screens: off-canvas
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed); // desktop

  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [lightbox, setLightbox] = useState(null);
  const [theme, setTheme] = useState(readTheme);
  const [docRequest, setDocRequest] = useState(null); // {documentId, conversationId, nonce}
  const searchRef = useRef('');

  const [models, setModels] = useState([]);
  const [limits, setLimits] = useState(null);
  const [selectedModel, setSelectedModel] = useState('auto');
  const composerRef = useRef(null);

  const refreshConversations = useCallback(() => {
    listConversations(searchRef.current).then(setConversations);
  }, []);

  // One toggle for both layouts: collapse/expand on desktop, open/close the drawer on small screens.
  const toggleSidebar = useCallback(() => {
    if (window.matchMedia?.(MOBILE_QUERY).matches) {
      setSidebarOpen((v) => !v);
      return;
    }
    setSidebarCollapsed((v) => {
      try {
        localStorage.setItem(SIDEBAR_KEY, v ? '0' : '1');
      } catch {
        /* per-browser convenience only */
      }
      return !v;
    });
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 's') {
        e.preventDefault();
        toggleSidebar();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [toggleSidebar]);

  const handleSearch = useCallback((q) => {
    searchRef.current = q;
    listConversations(q).then(setConversations);
  }, []);

  useEffect(() => {
    // 'system' follows the OS setting via prefers-color-scheme (see index.css).
    if (theme === 'system') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* per-browser convenience only */
    }
  }, [theme]);

  const openConversation = useCallback(async (id) => {
    setLoadingConversation(true);
    const conv = await getConversation(id);
    setLoadingConversation(false);
    if (conv) {
      setConversationId(conv.id);
      storeConversation(conv.id);
      setMessages(fromServer(conv));
    } else {
      storeConversation(null);
    }
  }, []);

  useEffect(() => {
    fetchModels().then((data) => {
      setModels(data.models || []);
      setLimits(data.limits || null);
    });
    refreshConversations();
    const stored = readStoredConversation();
    if (stored) openConversation(stored);
  }, [refreshConversations, openConversation]);

  const replaceMessage = (id, patch) =>
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)));

  /**
   * Stream one turn into the assistant message `msgId`. Text updates are batched
   * (~50 ms) so long answers do not re-render Markdown on every token.
   */
  const streamTurn = async ({ text, images, regenerate }, msgId, previous) => {
    setBusy(true);
    let acc = '';
    let flushTimer = null;
    const flush = () => {
      flushTimer = null;
      replaceMessage(msgId, { status: 'streaming', text: acc });
    };
    const final = await streamMessage(
      { message: text, model: selectedModel, images, conversationId, regenerate },
      (ev) => {
        if (ev.type === 'start') {
          if (ev.conversation_id && ev.conversation_id !== conversationId) {
            setConversationId(ev.conversation_id);
            storeConversation(ev.conversation_id);
          }
          replaceMessage(msgId, {
            model: ev.ollama_model, routing: ev.routing?.reason,
            routingExplanation: ev.routing?.explanation, ocr: ev.ocr || null,
          });
        } else if (ev.type === 'delta') {
          acc += ev.text;
          if (!flushTimer) flushTimer = setTimeout(flush, 50);
        }
      },
    );
    clearTimeout(flushTimer);
    setBusy(false);
    if (final.type === 'done') {
      if (final.conversation_id && final.conversation_id !== conversationId) {
        setConversationId(final.conversation_id);
        storeConversation(final.conversation_id);
      }
      replaceMessage(msgId, { ...fromResult(final), regenerateError: null });
      refreshConversations();
    } else if (previous) {
      // Regenerate failed: the backend kept the previous answer, so restore it.
      replaceMessage(msgId, { ...previous, status: 'done', regenerateError: `Regenerate failed: ${final.error}` });
    } else {
      replaceMessage(msgId, {
        status: 'error', text: acc,
        error: final.error || 'The local AI service did not return a response.',
        retry: { text, images },
      });
    }
  };

  const handleSend = (text, images = []) => {
    if (!text.trim() || busy) return;
    const pendingId = newId();
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: 'user', text, images },
      { id: pendingId, role: 'assistant', status: 'pending' },
    ]);
    streamTurn({ text, images }, pendingId);
  };

  // A failed turn is not stored by the backend, so retrying just sends it again.
  const handleRetry = (msg) => {
    if (busy || !msg.retry) return;
    replaceMessage(msg.id, { status: 'pending', error: null, text: '' });
    streamTurn(msg.retry, msg.id);
  };

  const handleRegenerate = (msg) => {
    if (busy || !conversationId) return;
    const previous = { ...msg };
    replaceMessage(msg.id, { status: 'pending', text: '', regenerateError: null, ocr: null });
    streamTurn({ regenerate: true }, msg.id, previous);
  };

  const handleNewChat = () => {
    setView('chat');
    setSidebarOpen(false);
    if (busy) return;
    setConversationId(null);
    storeConversation(null);
    setMessages([]);
    composerRef.current?.focus();
  };

  const handleSelect = (conv) => {
    setSidebarOpen(false);
    if (conv.document_id) {
      // Document Q&A conversation: open it in the Document Assistant.
      setView('documents');
      setDocRequest({ documentId: conv.document_id, conversationId: conv.id, nonce: Date.now() });
      return;
    }
    setView('chat');
    if (busy || conv.id === conversationId) return;
    openConversation(conv.id);
  };

  const handleRename = async (id, title) => {
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)));
    if (!(await renameConversation(id, title))) refreshConversations();
  };

  const handleDelete = async (conv) => {
    if (!window.confirm(`Delete "${conv.title || 'this conversation'}"? This also removes its images.`)) return;
    if (await deleteConversation(conv.id)) {
      setConversations((prev) => prev.filter((c) => c.id !== conv.id));
      if (conv.id === conversationId) {
        setConversationId(null);
        storeConversation(null);
        setMessages([]);
      }
    }
  };

  const handleSuggestion = (s) => {
    if (s.openDocuments) {
      setView('documents');
      return;
    }
    if (s.needsImage) {
      composerRef.current?.setText(s.prompt);
      composerRef.current?.openFilePicker();
      return;
    }
    handleSend(s.prompt, []);
  };

  const activeTitle = view === 'documents'
    ? 'Document Assistant'
    : conversations.find((c) => c.id === conversationId)?.title || 'New chat';
  const sidebarActiveId = view === 'documents' ? docRequest?.conversationId : conversationId;

  return (
    <div className={`app-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar
        view={view}
        onViewChange={(v) => { setView(v); setSidebarOpen(false); }}
        conversations={conversations}
        activeId={sidebarActiveId}
        onSelect={handleSelect}
        onNewChat={handleNewChat}
        onRename={handleRename}
        onDelete={handleDelete}
        open={sidebarOpen}
        collapsed={sidebarCollapsed}
        onClose={toggleSidebar}
        onSearch={handleSearch}
        theme={theme}
        onThemeChange={setTheme}
      />
      <div className="app-main">
        <Header
          title={activeTitle}
          onToggleSidebar={toggleSidebar}
          sidebarCollapsed={sidebarCollapsed}
          onNewChat={handleNewChat}
        />
        {view === 'chat' ? (
          <main className="chat-view">
            <ChatWindow
              messages={messages}
              loadingConversation={loadingConversation}
              onSuggestion={handleSuggestion}
              onImageClick={setLightbox}
              onRegenerate={handleRegenerate}
              onRetry={handleRetry}
            />
            <div className="chat-composer-wrap">
              <MessageInput
                ref={composerRef}
                onSend={handleSend}
                busy={busy}
                models={models}
                selectedModel={selectedModel}
                onModelChange={setSelectedModel}
                limits={limits}
              />
            </div>
          </main>
        ) : (
          <main className="docs-view">
            <Suspense fallback={<div className="chat-loading">Loading Document Assistant…</div>}>
              <DocumentsPage
                onImageClick={setLightbox}
                openRequest={docRequest}
                onConversationsChanged={refreshConversations}
              />
            </Suspense>
          </main>
        )}
      </div>
      <ImageLightbox src={lightbox} onClose={() => setLightbox(null)} />
    </div>
  );
}
