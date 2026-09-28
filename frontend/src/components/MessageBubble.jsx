import React, { useRef } from 'react';
import { RotateCcw, AlertTriangle, Sparkles, ScanText, ImagePlus } from 'lucide-react';
import Markdown from './LazyMarkdown';
import CopyButton from './CopyButton';
import { modelMeta } from '../utils/modelLabels';

/**
 * One chat turn, shared by General Chat and the Document Assistant.
 *
 * message: {
 *   role: 'user' | 'assistant', text, images?: [src], status?: 'pending'|'streaming'|'done'|'error',
 *   model?, routing?, routingExplanation?, info?: bool (notice such as "attach an image", no model used),
 *   ocr?: [{confidence}], error?, footnotes?: [string]
 * }
 * 'streaming' renders like 'done' with a cursor, so token streaming can be added later.
 */
export default function MessageBubble({ message, onImageClick, onRegenerate, onRetry, canRegenerate }) {
  const bodyRef = useRef(null);

  if (message.role === 'user') {
    return (
      <div className="msg msg-user">
        <div className="msg-user-content">
          {message.images?.length > 0 && (
            <div className={`msg-gallery count-${Math.min(message.images.length, 3)}`}>
              {message.images.map((src, idx) => (
                <button
                  type="button"
                  key={idx}
                  className="msg-gallery-item"
                  onClick={() => onImageClick?.(src)}
                  aria-label={`View attached image ${idx + 1}`}
                >
                  <img src={src} alt={`Attached ${idx + 1}`} loading="lazy" />
                </button>
              ))}
            </div>
          )}
          {message.text && <div className="msg-user-bubble">{message.text}</div>}
        </div>
      </div>
    );
  }

  const status = message.status || 'done';
  const meta = message.info ? null : modelMeta(message.model, message.routing);

  return (
    <div className={`msg msg-assistant is-${status}`}>
      <div className="msg-avatar" aria-hidden="true">
        <Sparkles size={15} />
      </div>
      <div className="msg-assistant-main">
        <div className="msg-meta">
          <span className="msg-author">MRPL Local AI</span>
          {status === 'pending' ? (
            <span className="msg-meta-detail thinking">Thinking<span className="thinking-dots" /></span>
          ) : meta ? (
            <span className="msg-meta-detail" title={message.routingExplanation || ''}>{meta}</span>
          ) : null}
          {message.ocr?.length > 0 && (
            <span
              className="msg-chip"
              title="Text was read from the image locally with PaddleOCR. Recognition confidence is PaddleOCR's own score, not measured accuracy."
            >
              <ScanText size={12} /> OCR · recognition confidence{' '}
              {message.ocr.map((o) => `${Math.round(o.confidence * 100)}%`).join(', ')}
            </span>
          )}
        </div>

        {status === 'pending' ? (
          <div className="msg-skeleton" aria-label="Generating response">
            <span /><span /><span />
          </div>
        ) : status === 'error' ? (
          <div className="msg-error" role="alert">
            <AlertTriangle size={15} />
            <span>{message.error || 'Something went wrong while generating a response.'}</span>
            {onRetry && (
              <button type="button" className="msg-inline-btn" onClick={onRetry}>
                <RotateCcw size={13} /> Retry
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="msg-body" ref={bodyRef}>
              {message.info ? (
                <div className="msg-notice">
                  <ImagePlus size={15} />
                  <span>{message.text}</span>
                </div>
              ) : (
                <Markdown text={message.text} />
              )}
              {status === 'streaming' && <span className="stream-cursor" />}
            </div>
            {message.footnotes?.length > 0 && (
              <div className="msg-footnotes">
                {message.footnotes.map((f, i) => <div key={i}>{f}</div>)}
              </div>
            )}
            {message.regenerateError && (
              <div className="msg-footnotes is-error">{message.regenerateError}</div>
            )}
            {status === 'done' && (
              <div className="msg-actions">
                <CopyButton
                  getText={() => bodyRef.current?.innerText?.trim() || message.text}
                  label="Copy"
                />
                {canRegenerate && onRegenerate && (
                  <button type="button" className="copy-action" onClick={onRegenerate} title="Regenerate response">
                    <RotateCcw size={14} />
                    <span>Regenerate</span>
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
