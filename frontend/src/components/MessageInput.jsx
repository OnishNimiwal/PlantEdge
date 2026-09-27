import React, { useState, useRef, useEffect } from 'react';
import { Send, Loader2, ImagePlus, X } from 'lucide-react';
import ModelSelector from './ModelSelector';

// Large images exhaust the 8 GB GPU in the vision model. The backend enforces the
// limit too; resizing here just keeps uploads small.
function resizeImage(file, maxSide) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Could not read image file.'));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error('Unsupported image file.'));
      img.onload = () => {
        const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL('image/jpeg', 0.9));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

export default function MessageInput({
  onSendMessage,
  disabled,
  models,
  selectedModel,
  onModelChange,
  limits,
}) {
  const maxImages = limits?.max_images_per_message || 1;
  const maxSide = limits?.vision_max_side || 1024;
  const [input, setInput] = useState('');
  const [images, setImages] = useState([]); // data URLs
  const [imageError, setImageError] = useState(null);
  const textareaRef = useRef(null);
  const fileRef = useRef(null);

  const isAuto = selectedModel === 'auto';
  const currentModel = models?.find((m) => m.id === selectedModel);
  // In auto mode an attached image makes the router pick the vision model.
  const supportsImages = isAuto || Boolean(currentModel?.supports_images);

  useEffect(() => {
    if (!disabled && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [disabled]);

  // Drop an attached image if the user switches to a text-only model.
  useEffect(() => {
    if (!supportsImages) {
      setImages([]);
      setImageError(null);
    }
  }, [supportsImages]);

  const handleSubmit = (e) => {
    if (e) e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || disabled) return;

    onSendMessage(trimmed, images);
    setInput('');
    setImages([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleInputChange = (e) => {
    setInput(e.target.value);
    // Auto adjust height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  };

  const handleFileChange = async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    if (!files.length) return;
    setImageError(null);
    if (files.some((f) => !['image/png', 'image/jpeg'].includes(f.type))) {
      setImageError('Only PNG and JPEG images are supported.');
      return;
    }
    const room = maxImages - images.length;
    if (files.length > room) {
      setImageError(`At most ${maxImages} image${maxImages > 1 ? 's' : ''} per message.`);
    }
    try {
      const resized = await Promise.all(files.slice(0, Math.max(room, 0)).map((f) => resizeImage(f, maxSide)));
      setImages((prev) => [...prev, ...resized]);
    } catch (err) {
      setImageError(err.message);
    }
  };

  return (
    <form className="input-form" onSubmit={handleSubmit}>
      {images.length > 0 && (
        <div className="attachment-row">
          {images.map((src, idx) => (
            <div className="attachment-preview" key={idx}>
              <img src={src} alt={`Attached ${idx + 1}`} />
              <button
                type="button"
                className="attachment-remove"
                onClick={() => setImages((prev) => prev.filter((_, i) => i !== idx))}
                title="Remove image"
                aria-label="Remove image"
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="input-container">
        {supportsImages && (
          <>
            <button
              type="button"
              className="attach-button"
              onClick={() => fileRef.current?.click()}
              disabled={disabled || images.length >= maxImages}
              title={`Attach up to ${maxImages} images (PNG/JPEG)`}
              aria-label="Attach image"
            >
              <ImagePlus size={18} />
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg"
              multiple={maxImages > 1}
              onChange={handleFileChange}
              hidden
            />
          </>
        )}
        <textarea
          ref={textareaRef}
          className="chat-textarea"
          value={input}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          placeholder={`Ask ${isAuto ? 'the local AI (auto model routing)' : currentModel?.name || 'the local Qwen model'}... (Press Enter to send, Shift+Enter for newline)`}
          rows={1}
          disabled={disabled}
        />
        <button
          type="submit"
          className="send-button"
          disabled={disabled || !input.trim()}
          title="Send message"
        >
          {disabled ? (
            <Loader2 size={18} className="spin-icon" />
          ) : (
            <Send size={18} />
          )}
        </button>
      </div>
      <div className="input-footer">
        <ModelSelector
          models={models}
          value={selectedModel}
          onChange={onModelChange}
          disabled={disabled}
        />
        <span className="privacy-hint">
          {imageError ? (
            <span className="attachment-error">{imageError}</span>
          ) : (
            '🔒 Strictly on-premise. Prompts and data never leave PC5.'
          )}
        </span>
      </div>
    </form>
  );
}
