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

/**
 * Conversations incl. Document Q&A (newest first, 50 per page); `q` searches titles + messages.
 * Returns {items, hasMore}.
 */
export async function listConversations(q = '', offset = 0) {
  try {
    const params = new URLSearchParams({ scope: 'all', offset: String(offset), limit: '50' });
    if (q.trim()) params.set('q', q.trim());
    const response = await fetch(`${API_BASE}/api/chat/conversations/?${params}`);
    if (!response.ok) return { items: [], hasMore: false };
    const data = await response.json();
    return { items: data.conversations || [], hasMore: Boolean(data.has_more) };
  } catch {
    return { items: [], hasMore: false };
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

/**
 * POST a streaming request and call onEvent for each NDJSON event
 * ({type: start|thinking|delta|done|error}). Errors raised before generation
 * starts come back as plain JSON; they are turned into a single error/done event.
 * Resolves with the final "done" event, or {type: 'error', error}.
 */
export async function postStream(url, body, onEvent) {
  let response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson, application/json' },
      body: JSON.stringify(body),
    });
  } catch (err) {
    const ev = { type: 'error', error: 'Unable to connect to the workbench server. Check that it is running.' };
    onEvent(ev);
    return ev;
  }
  const type = response.headers.get('Content-Type') || '';
  if (!type.includes('application/x-ndjson')) {
    // Validation errors, service errors, or the "attach an image" reply.
    const data = await response.json().catch(() => ({}));
    const ev = response.ok && data.success !== false
      ? { type: 'done', ...data }
      : { type: 'error', error: extractError(data, response.status) };
    onEvent(ev);
    return ev;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let last = { type: 'error', error: 'The response ended unexpectedly.' };
  for (;;) {
    let chunk;
    try {
      chunk = await reader.read();
    } catch {
      break;
    }
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    let nl;
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (!line) continue;
      let ev;
      try {
        ev = JSON.parse(line);
      } catch {
        continue;
      }
      onEvent(ev);
      if (ev.type === 'done' || ev.type === 'error') {
        // Terminal event: stop reading even if the connection is kept open (proxies, keep-alive).
        reader.cancel().catch(() => {});
        return ev;
      }
    }
  }
  if (last.type === 'error' && last.error === 'The response ended unexpectedly.') onEvent(last);
  return last;
}

/** Streamed chat turn (same body as sendMessage; regenerate supported). */
export function streamMessage({ message, model, images, conversationId, regenerate, think, editFrom, language }, onEvent) {
  const body = {};
  if (think) body.think = true;
  if (editFrom) body.edit_from = editFrom;
  if (language && language !== 'en') body.language = language;
  if (message) body.message = message;
  if (model) body.model = model;
  if (images && images.length) body.images = images;
  if (conversationId) body.conversation_id = conversationId;
  if (regenerate) body.regenerate = true;
  return postStream(`${API_BASE}/api/chat/stream/`, body, onEvent);
}

/**
 * Ask the server to load a model into GPU memory before the user sends (fire-and-forget).
 * The server skips it while another request is running, so it never evicts a busy model.
 */
const warmed = new Map();
export function warmUp(model) {
  if (!model || model === 'auto') return;
  const last = warmed.get(model) || 0;
  if (Date.now() - last < 60000) return; // at most once a minute per model
  warmed.set(model, Date.now());
  fetch(`${API_BASE}/api/models/warmup/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model }),
  }).catch(() => {});
}

/** Rate an answer: 'up' | 'down' | null (clear). Returns true on success. */
export async function sendFeedback(messageId, value) {
  try {
    const response = await fetch(`${API_BASE}/api/chat/messages/${messageId}/feedback/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value }),
    });
    return response.ok;
  } catch {
    return false;
  }
}
