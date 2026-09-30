import React from 'react';
import { ChevronDown } from 'lucide-react';
import { modelLabel } from '../utils/modelLabels';
import { useI18n } from '../utils/i18n';

const CAPABILITY = { reasoning: 'General', coding: 'Coding', vision: 'Vision' };

/**
 * Compact model picker. "Auto" lets the backend router choose; picking a model
 * overrides the router for the next messages.
 */
export default function ModelSelector({ models, value, onChange, disabled }) {
  const { t } = useI18n();
  if (!models || models.length === 0) return null;
  return (
    <label className="model-pill" title={t('Model: Auto lets the workbench pick the best local model')}>
      <select
        value={value || 'auto'}
        onChange={(e) => onChange && onChange(e.target.value)}
        disabled={disabled}
        aria-label={t('Model')}
      >
        <option value="auto">{t('Auto')}</option>
        {models.map((m) => (
          <option key={m.id} value={m.id}>
            {modelLabel(m.id)} · {CAPABILITY[m.capability] ? t(CAPABILITY[m.capability]) : m.capability}
          </option>
        ))}
      </select>
      <ChevronDown size={14} aria-hidden="true" />
    </label>
  );
}
