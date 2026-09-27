/**
 * API client for MRPL AI Workbench - Document Assistant
 * Handles document upload, listing, details, Q&A, summarization, docx export, and deletion.
 */

const API_BASE = import.meta.env.VITE_API_URL || '';

export async function getOCRConfig() {
  try {
    const response = await fetch(`${API_BASE}/api/documents/ocr-config/`);
    if (!response.ok) return { languages: [], default: 'en' };
    return await response.json();
  } catch {
    return { languages: [], default: 'en' };
  }
}

export async function uploadDocument(file, ocrLang) {
  const formData = new FormData();
  formData.append('file', file);
  if (ocrLang) formData.append('ocr_lang', ocrLang);

  try {
    const response = await fetch(`${API_BASE}/api/documents/upload/`, {
      method: 'POST',
      body: formData,
    });

    const data = await response.json();
    if (!response.ok) {
      return {
        success: false,
        error: data.error || (data.errors ? JSON.stringify(data.errors) : 'Upload failed'),
        status: response.status,
      };
    }
    return data;
  } catch (err) {
    return {
      success: false,
      error: 'Network error communicating with server during upload.',
      details: err.message,
    };
  }
}

export async function getDocuments() {
  try {
    const response = await fetch(`${API_BASE}/api/documents/`);
    const data = await response.json();
    if (!response.ok) {
      return { success: false, error: data.error || 'Failed to fetch documents' };
    }
    return data;
  } catch (err) {
    return { success: false, error: err.message };
  }
}

export async function getDocument(id) {
  try {
    const response = await fetch(`${API_BASE}/api/documents/${id}/`);
    const data = await response.json();
    if (!response.ok) {
      return { success: false, error: data.error || 'Failed to fetch document details' };
    }
    return data;
  } catch (err) {
    return { success: false, error: err.message };
  }
}

export async function askDocument(id, question, conversationId) {
  try {
    const body = { question };
    if (conversationId) body.conversation_id = conversationId;
    const response = await fetch(`${API_BASE}/api/documents/${id}/ask/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    const data = await response.json();
    if (!response.ok) {
      return {
        success: false,
        error: data.error || 'Failed to get answer from local AI',
        status: response.status,
      };
    }
    return data;
  } catch (err) {
    return { success: false, error: err.message };
  }
}

export async function summarizeDocument(id) {
  try {
    const response = await fetch(`${API_BASE}/api/documents/${id}/summary/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    const data = await response.json();
    if (!response.ok) {
      return {
        success: false,
        error: data.error || 'Failed to generate summary from local AI',
        status: response.status,
      };
    }
    return data;
  } catch (err) {
    return { success: false, error: err.message };
  }
}

export async function downloadDocumentReport(id, summaryText = '', defaultFilename = 'report.docx') {
  try {
    const response = await fetch(`${API_BASE}/api/documents/${id}/generate-report/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ summary: summaryText }),
    });

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      return {
        success: false,
        error: errData.error || `Failed to generate report (${response.status})`,
      };
    }

    // Extract filename from header if present
    const disposition = response.headers.get('Content-Disposition');
    let filename = defaultFilename;
    if (disposition && disposition.includes('filename=')) {
      const matches = disposition.match(/filename="?([^";]+)"?/);
      if (matches && matches[1]) {
        filename = matches[1];
      }
    }

    const blob = await response.blob();
    const downloadUrl = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = downloadUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(downloadUrl);

    return { success: true };
  } catch (err) {
    return { success: false, error: err.message };
  }
}

export async function deleteDocument(id) {
  try {
    const response = await fetch(`${API_BASE}/api/documents/${id}/`, {
      method: 'DELETE',
    });

    const data = await response.json();
    if (!response.ok) {
      return { success: false, error: data.error || 'Failed to delete document' };
    }
    return data;
  } catch (err) {
    return { success: false, error: err.message };
  }
}
