import React from 'react';
import { Globe, Share2, Building2, Lock } from 'lucide-react';
import { useI18n } from '../../utils/i18n';

export const CLASSIFICATION_LABELS = {
  public: 'Public',
  shareable: 'Shareable',
  internal: 'Internal',
  confidential: 'Confidential',
};

const ICONS = { public: Globe, shareable: Share2, internal: Building2, confidential: Lock };

const HINTS = {
  public: 'Public information; may leave the site.',
  shareable: 'May be shared with the central knowledge base.',
  internal: 'Stays on this site.',
  confidential: 'Confidential: never leaves this site.',
};

/** Data classification badge. `source` = default | user | detected (from the content scan). */
export default function ClassificationChip({ level, source, compact = false }) {
  const { t } = useI18n();
  if (!level) return null;
  const Icon = ICONS[level] || Building2;
  const hint = t(HINTS[level] || '') + (source === 'detected' ? ` ${t('Raised automatically: sensitive content was found.')}` : '');
  return (
    <span className={`class-chip is-${level}`} title={hint}>
      <Icon size={compact ? 11 : 12} aria-hidden="true" />
      {t(CLASSIFICATION_LABELS[level] || level)}
      {source === 'detected' && !compact && <span className="class-chip-auto">· {t('auto')}</span>}
    </span>
  );
}
