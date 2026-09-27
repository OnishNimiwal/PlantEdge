import React from 'react';
import { Cpu } from 'lucide-react';

/**
 * Local-model picker. "Auto" lets the backend router choose (Step 8);
 * picking a specific model overrides the router (Step 7 manual selection).
 */
export default function ModelSelector({ models, value, onChange, disabled }) {
  if (!models || models.length === 0) return null;

  return (
    <label className="model-selector" title="Choose which local model answers">
      <Cpu size={14} className="model-selector-icon" />
      <select
        className="model-select"
        value={value || ''}
        onChange={(e) => onChange && onChange(e.target.value)}
        disabled={disabled}
        aria-label="Local model"
      >
        <option value="auto">Auto (router)</option>
        {models.map((m) => (
          <option key={m.id} value={m.id}>
            {m.name} · {m.capability}
          </option>
        ))}
      </select>
    </label>
  );
}
