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
export async function sendMessage(message, model, images) {
  const url = `${API_BASE}/api/chat/`;
  const body = { message };
  if (model) body.model = model;
  if (images && images.length) body.images = images;

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
      error: "Unable to connect to Django backend. Ensure backend is running.",
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
