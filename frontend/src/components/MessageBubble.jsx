import React, { useState } from 'react';
import { User, Bot, Copy, Check } from 'lucide-react';

export default function MessageBubble({ message }) {
  const isUser = message.sender === 'user';
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy message:', err);
    }
  };

  return (
    <div className={`message-row ${isUser ? 'user-row' : 'bot-row'}`}>
      <div className={`avatar ${isUser ? 'user-avatar' : 'bot-avatar'}`}>
        {isUser ? <User size={18} /> : <Bot size={18} />}
      </div>

      <div className="message-content-wrapper">
        <div className="message-meta">
          <span className="sender-name">{isUser ? 'You' : 'MRPL Local AI'}</span>
          {!isUser && message.model && (
            <span className="message-model-tag">Model: {message.model}</span>
          )}
          {!isUser && message.routing && (
            <span className="message-model-tag message-routing-tag">Routing: {message.routing}</span>
          )}
          {!isUser && message.notice && (
            <span className="message-model-tag message-notice-tag">{message.notice}</span>
          )}
          <span className="message-time">{message.time || ''}</span>
        </div>

        <div className={`message-bubble ${isUser ? 'user-bubble' : 'bot-bubble'}`}>
          {message.images?.length > 0 && (
            <div className="message-images">
              {message.images.map((src, idx) => (
                <img key={idx} className="message-image" src={src} alt={`Attached ${idx + 1}`} />
              ))}
            </div>
          )}
          <div className="message-text">
            {message.text.split('\n').map((line, idx) => (
              <React.Fragment key={idx}>
                {line}
                {idx < message.text.split('\n').length - 1 && <br />}
              </React.Fragment>
            ))}
          </div>

          {!isUser && (
            <div className="message-actions">
              <button
                className="copy-btn"
                onClick={handleCopy}
                title="Copy response"
                aria-label="Copy response"
              >
                {copied ? <Check size={14} className="copied-icon" /> : <Copy size={14} />}
                <span>{copied ? 'Copied' : 'Copy'}</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
