/**
 * API client for MRPL AI Workbench
 * Communicates with the local Django REST Framework backend.
 */

const API_BASE = import.meta.env.VITE_API_URL || '';

/** Turn a DRF error body ({error} or {field: [msg]}) into one readable string. */
function extractError(data, status) {
  if (data?.error) return data.error;
  if (data?.message && typeof data.message === 'string') return data.message;
  if (data && typeof data === 'object') {
    const first = Object.values(data).flat().find((v) => typeof v === 'string');
    if (first) return first;
  }
  return `Server error (${status})`;
}

/**
 * @param {string} message
 * @param {string} [model]   registry id, e.g. "qwen3" (omitted -> backend default)
 * @param {string[]} [images] base64 / data-URL images (vision models only)
 */
export async function sendMessage(message, model, images, conversationId) {
  const url = `${API_BASE}/api/chat/`;
  const body = { message };
  if (model) body.model = model;
  if (images && images.length) body.images = images;
  if (conversationId) body.conversation_id = conversationId;

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    const data = await response.json();

    if (!response.ok) {
      return {
        success: false,
        error: extractError(data, response.status),
        status: response.status,
      };
    }

    return data;
  } catch (err) {
    return {
      success: false,
      error: "Unable to connect to the workbench server. Check that it is running.",
      details: err.message,
    };
  }
}

/** Fetch the local models registered on the backend. */
export async function fetchModels() {
  try {
    const response = await fetch(`${API_BASE}/api/models/`);
    if (!response.ok) return { models: [], default: null };
    return await response.json();
  } catch {
    return { models: [], default: null };
  }
}

/** Load a backend-held conversation (history is stored server-side). */
export async function getConversation(id) {
  try {
    const response = await fetch(`${API_BASE}/api/chat/conversations/${id}/`);
    if (!response.ok) return null;
    const data = await response.json();
    return data.conversation || null;
  } catch {
    return null;
  }
}

/** Most recent conversation for a document (Document Assistant Q&A), or null. */
export async function getLatestDocumentConversation(documentId) {
  try {
    const response = await fetch(`${API_BASE}/api/chat/conversations/?document=${documentId}`);
    if (!response.ok) return null;
    const data = await response.json();
    const latest = (data.conversations || [])[0];
    return latest ? getConversation(latest.id) : null;
  } catch {
    return null;
  }
}

/** Recent chat conversations (newest first, up to 50). */
export async function listConversations() {
  try {
    const response = await fetch(`${API_BASE}/api/chat/conversations/`);
    if (!response.ok) return [];
    const data = await response.json();
    return data.conversations || [];
  } catch {
    return [];
  }
}

export async function renameConversation(id, title) {
  try {
    const response = await fetch(`${API_BASE}/api/chat/conversations/${id}/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
    return response.ok;
  } catch {
    return false;
  }
}

export async function deleteConversation(id) {
  try {
    const response = await fetch(`${API_BASE}/api/chat/conversations/${id}/`, { method: 'DELETE' });
    return response.ok;
  } catch {
    return false;
  }
}

/** Re-run the last question of a conversation; the old answer is replaced on success. */
export async function regenerateLast(conversationId, model) {
  try {
    const response = await fetch(`${API_BASE}/api/chat/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: conversationId, regenerate: true, ...(model ? { model } : {}) }),
    });
    const data = await response.json();
    if (!response.ok) {
      return { success: false, error: extractError(data, response.status), status: response.status };
    }
    return data;
  } catch (err) {
    return { success: false, error: 'Unable to connect to the workbench server.', details: err.message };
  }
}
