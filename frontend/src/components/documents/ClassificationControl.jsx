import React, { useEffect, useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import { useI18n } from '../../utils/i18n';
import ClassificationChip, { CLASSIFICATION_LABELS } from './ClassificationChip';
import { getPolicy, setClassification } from '../../api/knowledgeApi';

const ORDER = ['public', 'shareable', 'internal', 'confidential'];

/** Classification badge + change control for one document (header of the document viewer). */
export default function ClassificationControl({ document, onChanged }) {
  const { t } = useI18n();
  const [levels, setLevels] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => { getPolicy().then((p) => setLevels(p.levels || [])); }, []);

  const change = async (level) => {
    if (level === document.classification) return;
    setError(null);
    let reason = '';
    if (ORDER.indexOf(level) < ORDER.indexOf(document.classification)) {
      reason = window.prompt(t('Why may this document be {level}? (recorded in the audit log)',
        { level: t(CLASSIFICATION_LABELS[level]) })) || '';
      if (!reason.trim()) return;
    }
    setBusy(true);
    const res = await setClassification(document.id, level, reason);
    setBusy(false);
    if (res.success) onChanged?.(res.document);
    else setError(res.error);
  };

  const markers = document.sensitivity_markers || [];
  return (
    <>
      <ClassificationChip level={document.classification} source={document.classification_source} />
      {levels.length > 0 && (
        <select
          className="model-select class-select"
          value={document.classification}
          onChange={(e) => change(e.target.value)}
          disabled={busy}
          aria-label={t('Change classification')}
          title={t('Change classification')}
        >
          {levels.map((l) => (
            <option key={l.id} value={l.id}>{t(CLASSIFICATION_LABELS[l.id] || l.id)}</option>
          ))}
        </select>
      )}
      {markers.length > 0 && (
        <span
          className="meta-badge warning"
          title={t('Found by the automatic content scan. These sections never leave the site, whatever the classification.')}
        >
          <ShieldAlert size={12} />
          {t('Sensitive content')}: {markers.map((m) => `${t(m.label)}${m.count > 1 ? ` (${m.count})` : ''}`).join(', ')}
        </span>
      )}
      {error && <span className="meta-badge warning" role="alert">{error}</span>}
    </>
  );
}
