import React, { useEffect } from 'react';
import { X } from 'lucide-react';

/** Full-size image viewer. Closes on Esc, backdrop click or the close button. */
export default function ImageLightbox({ src, onClose }) {
  useEffect(() => {
    if (!src) return undefined;
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [src, onClose]);

  if (!src) return null;
  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label="Image preview" onClick={onClose}>
      <button type="button" className="lightbox-close" onClick={onClose} aria-label="Close preview">
        <X size={20} />
      </button>
      <img src={src} alt="Attachment" onClick={(e) => e.stopPropagation()} />
    </div>
  );
}
