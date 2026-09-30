import React, { useEffect, useRef, useState } from 'react';
import {
  RotateCcw, AlertTriangle, Sparkles, ScanText, ImagePlus, CheckCircle2, Info, Pencil, ThumbsUp, ThumbsDown,
} from 'lucide-react';
import Markdown from './LazyMarkdown';
import CopyButton from './CopyButton';
import { modelMeta } from '../utils/modelLabels';
import { useI18n } from '../utils/i18n';
import { sendFeedback } from '../api/chatApi';

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
/**
 * What the answer was based on (document / image / OCR text / general knowledge / code).
 * Set by the backend from what the model actually received; it is not a correctness score.
 */
const BASIS_LABELS = {
  document: 'Based on uploaded document',
  image: 'Based on provided image',
  image_text: 'Based on text read from the provided image (OCR)',
  general: 'General AI response',
  code: 'Generated code — not executed',
};
const UNDETERMINED_LABELS = {
  document: 'Not found in the provided document',
  image: 'Cannot be determined from the provided image',
  image_text: 'Not found in the text read from the image',
};
// Backend check messages (documents/services.py, chat/views.py) -> translatable templates.
const WARNING_PATTERNS = [
  [/^Values? not found in the document: (.+)$/, 'Values not found in the document: {v}'],
  [/^Values? not found in the OCR text: (.+)$/, 'Values not found in the OCR text: {v}'],
  [/^Cited pages? not given to the model: (.+)$/, 'Cited pages not given to the model: {v}'],
  [/^The answer says the code was run or tested/, 'The answer says the code was run or tested, but the workbench did not execute it.'],
];

function translateWarning(t, w) {
  for (const [re, key] of WARNING_PATTERNS) {
    const m = w.match(re);
    if (m) return t(key, { v: m[1] });
  }
  return w;
}

export function BasisIndicator({ basis }) {
  const { t } = useI18n();
  if (!basis?.label) return null;
  const grounded = ['document', 'image', 'image_text'].includes(basis.type);
  const Icon = basis.undetermined ? AlertTriangle : grounded ? CheckCircle2 : Info;
  const tone = basis.undetermined ? 'is-warn' : grounded ? 'is-grounded' : 'is-info';
  const known = (basis.undetermined ? UNDETERMINED_LABELS : BASIS_LABELS)[basis.type];
  return (
    <div className="basis-wrap">
      <div
        className={`basis ${tone}`}
        title={t('Shows what this answer was based on. It does not guarantee that the answer is correct.')}
      >
        <Icon size={13} aria-hidden="true" />
        <span>{known ? t(known) : basis.label}</span>
        {basis.detail && <span className="basis-detail">· {basis.detail}</span>}
      </div>
      {basis.warnings?.map((w) => (
        <div key={w} className="basis-warning" title={t('Automatic check against the source (not a model judgement)')}>
          <AlertTriangle size={12} aria-hidden="true" /> {translateWarning(t, w)}
        </div>
      ))}
    </div>
  );
}

/** Seconds since `since` (ms timestamp), updated every second while mounted. */
function useElapsed(since, active) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return since ? Math.max(0, Math.round((now - since) / 1000)) : 0;
}

const STAGE_LABELS = {
  vision: 'Reading the image with Qwen2.5-VL 7B',
  coding: 'Writing code with Qwen2.5-Coder 7B',
};

function pendingLabel(message, t) {
  if (message.stage) return STAGE_LABELS[message.stage] ? t(STAGE_LABELS[message.stage]) : message.stageLabel || message.stage;
  if (message.loadingModel) return t('Loading {model} into GPU memory', { model: message.loadingModelName || t('model') });
  if (message.thinking) return t('Thinking step by step');
  return t('Thinking');
}

/** Thumbs up / down on a stored answer (shown per model on the dashboard; an opinion, not accuracy). */
function FeedbackButtons({ message }) {
  const { t } = useI18n();
  const [value, setValue] = useState(message.feedback || null);
  useEffect(() => { setValue(message.feedback || null); }, [message.serverId, message.feedback]);
  if (!message.serverId) return null;

  const rate = async (next) => {
    const target = value === next ? null : next; // clicking the active rating clears it
    const before = value;
    setValue(target);
    if (!(await sendFeedback(message.serverId, target))) setValue(before);
  };
  return (
    <>
      <button
        type="button"
        className={`copy-action feedback-btn ${value === 'up' ? 'is-active' : ''}`}
        onClick={() => rate('up')}
        aria-pressed={value === 'up'}
        title={t('Helpful')}
        aria-label={t('Helpful')}
      >
        <ThumbsUp size={14} />
      </button>
      <button
        type="button"
        className={`copy-action feedback-btn ${value === 'down' ? 'is-active is-down' : ''}`}
        onClick={() => rate('down')}
        aria-pressed={value === 'down'}
        title={t('Not helpful')}
        aria-label={t('Not helpful')}
      >
        <ThumbsDown size={14} />
      </button>
    </>
  );
}

/** A user message with inline editing (Save & submit replaces this turn and everything after it). */
function UserMessage({ message, onImageClick, onEdit, busy }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.text || '');
  const areaRef = useRef(null);

  useEffect(() => {
    if (editing) {
      const el = areaRef.current;
      el?.focus();
      el?.setSelectionRange(el.value.length, el.value.length);
    }
  }, [editing]);

  const canEdit = Boolean(onEdit && message.serverId);
  const save = () => {
    const text = draft.trim();
    if (!text || busy) return;
    setEditing(false);
    if (text !== message.text) onEdit(message, text);
  };

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
                aria-label={t('View attached image {n}', { n: idx + 1 })}
              >
                <img src={src} alt={t('Attached {n}', { n: idx + 1 })} loading="lazy" />
              </button>
            ))}
          </div>
        )}
        {editing ? (
          <div className="msg-edit">
            <textarea
              ref={areaRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setEditing(false);
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); save(); }
              }}
              rows={Math.min(8, Math.max(2, draft.split('\n').length))}
              aria-label={t('Edit message')}
            />
            <div className="msg-edit-hint">{t('Editing replaces this message and everything after it.')}</div>
            <div className="msg-edit-actions">
              <button type="button" className="btn-ghost" onClick={() => { setEditing(false); setDraft(message.text || ''); }}>
                {t('Cancel')}
              </button>
              <button type="button" className="btn-primary" onClick={save} disabled={busy || !draft.trim()}>
                {t('Save & submit')}
              </button>
            </div>
          </div>
        ) : (
          <>
            {message.text && <div className="msg-user-bubble">{message.text}</div>}
            {canEdit && (
              <div className="msg-user-actions">
                <button
                  type="button"
                  className="copy-action"
                  onClick={() => { setDraft(message.text || ''); setEditing(true); }}
                  disabled={busy}
                  title={t('Edit message')}
                  aria-label={t('Edit message')}
                >
                  <Pencil size={13} />
                </button>
                <CopyButton getText={() => message.text} iconOnly />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function MessageBubble({ message, onImageClick, onRegenerate, onRetry, canRegenerate, onEdit, busy }) {
  const { t } = useI18n();
  const bodyRef = useRef(null);
  const status = message.status || 'done';
  const elapsed = useElapsed(message.startedAt, status === 'pending');

  if (message.role === 'user') {
    return <UserMessage message={message} onImageClick={onImageClick} onEdit={onEdit} busy={busy} />;
  }

  const meta = message.info ? null : modelMeta(message.model, message.routing, t);

  return (
    <div className={`msg msg-assistant is-${status}`}>
      <div className="msg-avatar" aria-hidden="true">
        <Sparkles size={15} />
      </div>
      <div className="msg-assistant-main">
        <div className="msg-meta">
          <span className="msg-author">{t('MRPL Local AI')}</span>
          {status === 'pending' ? (
            <span className="msg-meta-detail thinking" aria-live="polite">
              {pendingLabel(message, t)}<span className="thinking-dots" />
              {elapsed >= 3 && <span className="elapsed"> {elapsed}s</span>}
            </span>
          ) : meta ? (
            <span className="msg-meta-detail" title={message.routingExplanation || ''}>{meta}</span>
          ) : null}
          {message.ocr?.length > 0 && (
            <span
              className="msg-chip"
              title={t("Text was read from the image locally with PaddleOCR. Recognition confidence is PaddleOCR's own score, not measured accuracy.")}
            >
              <ScanText size={12} /> {t('OCR · recognition confidence')}{' '}
              {message.ocr.map((o) => `${Math.round(o.confidence * 100)}%`).join(', ')}
            </span>
          )}
        </div>

        {status === 'pending' ? (
          <div className="msg-skeleton" aria-label={t('Generating response')}>
            <span /><span /><span />
          </div>
        ) : status === 'error' ? (
          <div className="msg-error" role="alert">
            <AlertTriangle size={15} />
            <span>{message.error || t('Something went wrong while generating a response.')}</span>
            {onRetry && (
              <button type="button" className="msg-inline-btn" onClick={onRetry}>
                <RotateCcw size={13} /> {t('Retry')}
              </button>
            )}
          </div>
        ) : (
          <>
            {!message.info && status === 'done' && <BasisIndicator basis={message.basis} />}
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
                {message.footnotes.map((f, i) => <div key={i}>{t(f)}</div>)}
              </div>
            )}
            {message.regenerateError && (
              <div className="msg-footnotes is-error">{message.regenerateError}</div>
            )}
            {status === 'done' && (
              <div className="msg-actions">
                <CopyButton
                  getText={() => bodyRef.current?.innerText?.trim() || message.text}
                  label={t('Copy')}
                />
                {canRegenerate && onRegenerate && (
                  <button type="button" className="copy-action" onClick={onRegenerate} title={t('Regenerate response')} disabled={busy}>
                    <RotateCcw size={14} />
                    <span>{t('Regenerate')}</span>
                  </button>
                )}
                <FeedbackButtons message={message} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
