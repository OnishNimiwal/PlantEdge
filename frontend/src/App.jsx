import React, { useEffect, useState } from 'react';
import Header from './components/Header';
import ChatWindow from './components/ChatWindow';
import MessageInput from './components/MessageInput';
import DocumentsPage from './components/documents/DocumentsPage';
import { sendMessage, fetchModels } from './api/chatApi';

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

  useEffect(() => {
    fetchModels().then((data) => {
      setModels(data.models || []);
      setLimits(data.limits || null);
    });
  }, []);

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
      const result = await sendMessage(text, selectedModel, images);

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
            />
          </div>
        ) : (
          <DocumentsPage />
        )}
      </main>
    </div>
  );
}
