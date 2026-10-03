/**
 * API client for the local knowledge base (Qdrant Edge) and data classification.
 */

import { postStream, getConversation } from './chatApi';

const API_BASE = import.meta.env.VITE_API_URL || '';

/** Streamed knowledge-base question (or regenerate of the last answer). */
export async function streamKnowledgeQuestion({ question, conversationId, regenerate, think, language }, onEvent) {
  const body = {};
  if (think) body.think = true;
  if (language && language !== 'en') body.language = language;
  if (question) body.question = question;
  if (conversationId) body.conversation_id = conversationId;
  if (regenerate) body.regenerate = true;
  return postStream(`${API_BASE}/api/knowledge/ask/stream/`, body, onEvent);
}

export async function getLatestKnowledgeConversation() {
  try {
    const response = await fetch(`${API_BASE}/api/chat/conversations/?kind=knowledge`);
    if (!response.ok) return null;
    const data = await response.json();
    const latest = (data.conversations || [])[0];
    return latest ? getConversation(latest.id) : null;
  } catch {
    return null;
  }
}

export async function getKnowledgeStatus() {
  try {
    const response = await fetch(`${API_BASE}/api/knowledge/status/`);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

const FALLBACK_POLICY = {
  levels: [
    { id: 'public', may_leave_site: true },
    { id: 'shareable', may_leave_site: true },
    { id: 'internal', may_leave_site: false },
    { id: 'confidential', may_leave_site: false },
  ],
  default: 'internal',
  allow_override: false,
};

export async function getPolicy() {
  try {
    const response = await fetch(`${API_BASE}/api/knowledge/policy/`);
    return response.ok ? await response.json() : FALLBACK_POLICY;
  } catch {
    return FALLBACK_POLICY;
  }
}

/** Change a document's classification. Lowering needs a reason; the server may refuse (403). */
export async function setClassification(documentId, classification, reason = '') {
  try {
    const response = await fetch(`${API_BASE}/api/documents/${documentId}/classification/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ classification, reason }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) return { success: false, error: data.error || 'The classification could not be changed.' };
    return data;
  } catch (err) {
    return { success: false, error: err.message };
  }
}
