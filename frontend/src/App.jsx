import React, { useCallback, useEffect, useRef, useState } from 'react';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import ChatWindow from './components/ChatWindow';
import MessageInput from './components/MessageInput';
import ImageLightbox from './components/ImageLightbox';
import DocumentsPage from './components/documents/DocumentsPage';
import {
  sendMessage, fetchModels, getConversation, listConversations,
  renameConversation, deleteConversation, regenerateLast,
} from './api/chatApi';

const CONVERSATION_KEY = 'mrpl.chat.conversationId';

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
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [lightbox, setLightbox] = useState(null);

  const [models, setModels] = useState([]);
  const [limits, setLimits] = useState(null);
  const [selectedModel, setSelectedModel] = useState('auto');
  const composerRef = useRef(null);

  const refreshConversations = useCallback(() => {
    listConversations().then(setConversations);
  }, []);

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

  const runTurn = async (text, images, pendingId) => {
    setBusy(true);
    const result = await sendMessage(text, selectedModel, images, conversationId);
    setBusy(false);
    if (result?.conversation_id && result.conversation_id !== conversationId) {
      setConversationId(result.conversation_id);
      storeConversation(result.conversation_id);
    }
    if (result?.success && typeof result.response === 'string') {
      replaceMessage(pendingId, fromResult(result));
      refreshConversations();
    } else {
      replaceMessage(pendingId, {
        status: 'error',
        error: result?.error || 'The local AI service did not return a response.',
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
    runTurn(text, images, pendingId);
  };

  // A failed turn is not stored by the backend, so retrying just sends it again.
  const handleRetry = (msg) => {
    if (busy || !msg.retry) return;
    replaceMessage(msg.id, { status: 'pending', error: null });
    runTurn(msg.retry.text, msg.retry.images, msg.id);
  };

  const handleRegenerate = async (msg) => {
    if (busy || !conversationId) return;
    const previous = { ...msg };
    replaceMessage(msg.id, { status: 'pending', regenerateError: null });
    setBusy(true);
    const result = await regenerateLast(conversationId, selectedModel);
    setBusy(false);
    if (result?.success && typeof result.response === 'string') {
      replaceMessage(msg.id, { ...fromResult(result), regenerateError: null });
      refreshConversations();
    } else {
      // The backend keeps the previous answer when regeneration fails.
      replaceMessage(msg.id, { ...previous, status: 'done', regenerateError: `Regenerate failed: ${result?.error || 'unknown error'}` });
    }
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

  const handleSelect = (id) => {
    setView('chat');
    setSidebarOpen(false);
    if (busy || id === conversationId) return;
    openConversation(id);
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

  return (
    <div className="app-shell">
      <Sidebar
        view={view}
        onViewChange={(v) => { setView(v); setSidebarOpen(false); }}
        conversations={conversations}
        activeId={conversationId}
        onSelect={handleSelect}
        onNewChat={handleNewChat}
        onRename={handleRename}
        onDelete={handleDelete}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />
      <div className="app-main">
        <Header title={activeTitle} onMenu={() => setSidebarOpen(true)} />
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
          <DocumentsPage onImageClick={setLightbox} />
        )}
      </div>
      <ImageLightbox src={lightbox} onClose={() => setLightbox(null)} />
    </div>
  );
}
