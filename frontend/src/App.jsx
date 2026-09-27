import React, { useEffect, useState } from 'react';
import Header from './components/Header';
import ChatWindow from './components/ChatWindow';
import MessageInput from './components/MessageInput';
import DocumentsPage from './components/documents/DocumentsPage';
import { sendMessage, fetchModels, getConversation } from './api/chatApi';

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

function toUiMessages(conversation) {
  return conversation.messages.map((m, idx) => ({
    id: `${conversation.id}-${idx}`,
    sender: m.role === 'user' ? 'user' : 'bot',
    text: m.content,
    time: new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    images: m.images || [],
    model: m.role === 'assistant' ? m.model : null,
    routing: m.role === 'assistant' ? m.routing_reason : null,
  }));
}

export default function App() {
  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'documents'

  // Chat State
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  // Local model registry. 'auto' = backend router picks; a model id = manual choice.
  const [models, setModels] = useState([]);
  const [limits, setLimits] = useState(null);
  const [selectedModel, setSelectedModel] = useState('auto');
  const [conversationId, setConversationId] = useState(null);

  useEffect(() => {
    fetchModels().then((data) => {
      setModels(data.models || []);
      setLimits(data.limits || null);
    });
    const stored = readStoredConversation();
    if (stored) {
      getConversation(stored).then((conv) => {
        if (conv) {
          setConversationId(conv.id);
          setMessages(toUiMessages(conv));
        } else {
          storeConversation(null);
        }
      });
    }
  }, []);

  const handleNewChat = () => {
    setConversationId(null);
    storeConversation(null);
    setMessages([]);
    setError(null);
  };

  const modelName = (id) =>
    id === 'auto' ? 'Auto (router)' : models.find((m) => m.id === id)?.name || id;

  const formatTime = () => {
    const now = new Date();
    return now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const handleSendMessage = async (text, images = []) => {
    if (!text.trim() || isLoading) return;

    setError(null);
    const userMsg = {
      id: Date.now().toString(),
      sender: 'user',
      text: text,
      time: formatTime(),
      images,
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const result = await sendMessage(text, selectedModel, images, conversationId);
      if (result?.conversation_id && result.conversation_id !== conversationId) {
        setConversationId(result.conversation_id);
        storeConversation(result.conversation_id);
      }

      if (result && result.success && result.response) {
        const botMsg = {
          id: (Date.now() + 1).toString(),
          sender: 'bot',
          text: result.response,
          time: formatTime(),
          model: result.needs_image ? null : result.ollama_model || modelName(result.model) || 'local-ollama',
          routing: result.routing?.reason || null,
          routingExplanation: result.routing?.explanation || null,
          notice: result.needs_image ? 'No model was called' : null,
        };
        setMessages((prev) => [...prev, botMsg]);
      } else {
        const errorMsg = result?.error || "Unable to get response from local AI server.";
        setError(errorMsg);
      }
    } catch (err) {
      setError(err.message || "Failed to communicate with AI chat endpoint.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSuggestionClick = (prompt) => {
    handleSendMessage(prompt);
  };

  return (
    <div className="app-container">
      <Header
        activeTab={activeTab}
        onTabChange={setActiveTab}
        modelName={activeTab === 'chat' && selectedModel ? modelName(selectedModel) : null}
      />

      <main className="main-content">
        {activeTab === 'chat' ? (
          <div className="chat-layout">
            <ChatWindow
              messages={messages}
              isLoading={isLoading}
              error={error}
              onSuggestionClick={handleSuggestionClick}
            />
            <MessageInput
              onSendMessage={handleSendMessage}
              disabled={isLoading}
              models={models}
              selectedModel={selectedModel}
              onModelChange={setSelectedModel}
              limits={limits}
              onNewChat={handleNewChat}
              hasHistory={messages.length > 0}
            />
          </div>
        ) : (
          <DocumentsPage />
        )}
      </main>
    </div>
  );
}
