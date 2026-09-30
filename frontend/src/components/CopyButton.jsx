import React, { useEffect, useRef, useState } from 'react';
import { Copy, Check } from 'lucide-react';
import { useI18n } from '../utils/i18n';

async function writeClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // Fallback for plain-http LAN deployments, where navigator.clipboard is unavailable.
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  try {
    document.execCommand('copy');
  } finally {
    document.body.removeChild(area);
  }
}

/**
 * "Copy" -> "Copied ✓" for ~2 s. `getText` is called on click so the latest
 * content (e.g. rendered text) is copied.
 */
export default function CopyButton({ getText, label, className = '', iconOnly = false }) {
  const { t } = useI18n();
  const text = label ?? t('Copy');
  const done = t('Copied');
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);

  const handleClick = async () => {
    try {
      await writeClipboard(getText());
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.warn('Copy failed', err);
    }
  };

  return (
    <button
      type="button"
      className={`copy-action ${copied ? 'is-copied' : ''} ${className}`}
      onClick={handleClick}
      title={copied ? done : text || t('Copy')}
      aria-label={copied ? done : text || t('Copy')}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
      {!iconOnly && text && <span>{copied ? `${done} ✓` : text}</span>}
    </button>
  );
}
