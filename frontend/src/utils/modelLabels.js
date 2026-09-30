/**
 * User-facing labels for models and routing decisions.
 * Internal identifiers (Ollama tags, routing reasons) never reach the UI directly.
 */

const MODEL_LABELS = {
  'qwen3:8b': 'Qwen3 8B',
  'qwen2.5-coder:7b': 'Qwen2.5-Coder 7B',
  'qwen2.5vl:7b': 'Qwen2.5-VL 7B',
  qwen3: 'Qwen3 8B',
  'qwen-coder': 'Qwen2.5-Coder 7B',
  'qwen-vl': 'Qwen2.5-VL 7B',
};

const ROUTING_LABELS = {
  general_reasoning: 'General',
  coding: 'Coding',
  vision: 'Vision',
  ocr_text: 'Document text · OCR',
  vision_ocr: 'Vision + OCR',
  vision_coding: 'Image → Code',
  manual: 'Selected manually',
};

export function modelLabel(idOrTag) {
  if (!idOrTag) return null;
  return MODEL_LABELS[idOrTag] || idOrTag;
}

export function routingLabel(reason, t = (s) => s) {
  if (!reason) return null;
  return ROUTING_LABELS[reason] ? t(ROUTING_LABELS[reason]) : reason;
}

/** "Qwen2.5-Coder 7B · Coding" (pass the i18n `t` to translate the routing part) */
export function modelMeta(model, reason, t) {
  return [modelLabel(model), routingLabel(reason, t)].filter(Boolean).join(' · ');
}
