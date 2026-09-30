/** Dashboard API: usage statistics and system/model health (fetched on demand, no polling). */

const API_BASE = import.meta.env.VITE_API_URL || '';

async function getJson(path) {
  try {
    const response = await fetch(`${API_BASE}${path}`);
    if (!response.ok) return { error: `The workbench server returned an error (${response.status}).` };
    return await response.json();
  } catch {
    return { error: 'Unable to reach the workbench server.' };
  }
}

/** Aggregated usage; "today" uses the viewer's local day. */
export function getUsage() {
  return getJson(`/api/dashboard/usage/?tz_offset=${new Date().getTimezoneOffset()}`);
}

export function getSystemStatus() {
  return getJson('/api/dashboard/status/');
}

/** Opt-in functional test: target 'ocr' or a model id. Loads OCR / the model and runs a tiny test. */
export async function runDeepCheck(target) {
  try {
    const response = await fetch(`${API_BASE}/api/dashboard/deep-check/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) return { success: false, detail: data.error || `Server error (${response.status}).` };
    return data;
  } catch {
    return { success: false, detail: 'Unable to reach the workbench server.' };
  }
}
