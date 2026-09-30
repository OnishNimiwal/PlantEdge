import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { ArrowUp, Paperclip, X, Loader2, Brain } from 'lucide-react';
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

/**
 * Composer: textarea (Enter = send, Shift+Enter = newline), attachments, model picker.
 * Imperative handle: setText(text), focus(), openFilePicker().
 */
const MessageInput = forwardRef(function MessageInput(
  {
    onSend,
    busy,
    models,
    selectedModel,
    onModelChange,
    limits,
    allowAttachments = true,
    showModelPicker = true,
    placeholder = 'Ask anything…',
    think = false,
    onThinkChange,
    thinkAvailable = true,
    onImagesAttached,
    footnote = 'Runs on-premise with local models. Responses can contain mistakes — verify important information.',
  },
  ref,
) {
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
  const supportsImages = allowAttachments && (isAuto || Boolean(currentModel?.supports_images));

  const autoSize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  };

  useImperativeHandle(ref, () => ({
    setText: (text) => {
      setInput(text);
      requestAnimationFrame(() => {
        autoSize();
        textareaRef.current?.focus();
      });
    },
    focus: () => textareaRef.current?.focus(),
    openFilePicker: () => fileRef.current?.click(),
  }));

  useEffect(() => {
    if (!busy) textareaRef.current?.focus();
  }, [busy]);

  // Drop attached images if the user switches to a text-only model.
  useEffect(() => {
    if (!supportsImages) {
      setImages([]);
      setImageError(null);
    }
  }, [supportsImages]);

  const submit = (e) => {
    e?.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || busy) return;
    onSend(trimmed, images);
    setInput('');
    setImages([]);
    setImageError(null);
    requestAnimationFrame(autoSize);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const handleFiles = async (e) => {
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
      setImageError(`You can attach up to ${maxImages} image${maxImages > 1 ? 's' : ''} per message.`);
    }
    try {
      const resized = await Promise.all(files.slice(0, Math.max(room, 0)).map((f) => resizeImage(f, maxSide)));
      setImages((prev) => [...prev, ...resized]);
      onImagesAttached?.(); // e.g. start loading the vision model while the user types
    } catch (err) {
      setImageError(err.message);
    }
  };

  return (
    <form className="composer" onSubmit={submit}>
      <div className={`composer-box ${busy ? 'is-busy' : ''}`}>
        {images.length > 0 && (
          <div className="composer-attachments">
            {images.map((src, idx) => (
              <div className="composer-thumb" key={idx}>
                <img src={src} alt={`Attachment ${idx + 1}`} />
                <button
                  type="button"
                  onClick={() => setImages((prev) => prev.filter((_, i) => i !== idx))}
                  aria-label="Remove image"
                  title="Remove image"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        )}

        <textarea
          ref={textareaRef}
          className="composer-input"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            autoSize();
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
          aria-label="Message"
        />

        <div className="composer-toolbar">
          <div className="composer-tools">
            {supportsImages && (
              <>
                <button
                  type="button"
                  className="icon-btn"
                  onClick={() => fileRef.current?.click()}
                  disabled={images.length >= maxImages}
                  title={`Attach images (PNG/JPEG, up to ${maxImages})`}
                  aria-label="Attach images"
                >
                  <Paperclip size={18} />
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/png,image/jpeg"
                  multiple={maxImages > 1}
                  onChange={handleFiles}
                  hidden
                />
              </>
            )}
            {showModelPicker && (
              <ModelSelector models={models} value={selectedModel} onChange={onModelChange} disabled={busy} />
            )}
            {onThinkChange && thinkAvailable && (
              <button
                type="button"
                className={`think-toggle ${think ? 'is-on' : ''}`}
                onClick={() => onThinkChange(!think)}
                aria-pressed={think}
                title={think
                  ? 'Think deeper is on: step-by-step reasoning, slower answers'
                  : 'Think deeper: step-by-step reasoning for hard questions (slower)'}
              >
                <Brain size={15} />
                <span>{think ? 'Thinking on' : 'Think deeper'}</span>
              </button>
            )}
          </div>
          <button
            type="submit"
            className="send-btn"
            disabled={busy || !input.trim()}
            title="Send (Enter)"
            aria-label="Send message"
          >
            {busy ? <Loader2 size={18} className="spin" /> : <ArrowUp size={18} />}
          </button>
        </div>
      </div>
      <div className={`composer-footnote ${imageError ? 'is-error' : ''}`}>
        {imageError || footnote}
      </div>
    </form>
  );
});

export default MessageInput;
