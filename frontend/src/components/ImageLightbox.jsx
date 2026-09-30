import React, { useEffect } from 'react';
import { X } from 'lucide-react';
import { useI18n } from '../utils/i18n';

/** Full-size image viewer. Closes on Esc, backdrop click or the close button. */
export default function ImageLightbox({ src, onClose }) {
  const { t } = useI18n();
  useEffect(() => {
    if (!src) return undefined;
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [src, onClose]);

  if (!src) return null;
  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label={t('Image preview')} onClick={onClose}>
      <button type="button" className="lightbox-close" onClick={onClose} aria-label={t('Close preview')}>
        <X size={20} />
      </button>
      <img src={src} alt={t('Attachment')} onClick={(e) => e.stopPropagation()} />
    </div>
  );
}
