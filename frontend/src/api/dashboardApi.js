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
