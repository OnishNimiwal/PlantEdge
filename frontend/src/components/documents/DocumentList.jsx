import React from 'react';
import { FileText, Trash2, Calendar, FileCode, Check } from 'lucide-react';

export default function DocumentList({
  documents,
  selectedDocId,
  onSelectDoc,
  onDeleteDoc,
  loading,
}) {
  const formatDate = (dateStr) => {
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString([], {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return dateStr;
    }
  };

  if (loading && documents.length === 0) {
    return <div className="doc-list-loading">Loading documents...</div>;
  }

  if (documents.length === 0) {
    return (
      <div className="doc-list-empty">
        <FileText size={36} className="empty-docs-icon" />
        <p>No documents uploaded yet.</p>
        <span>Upload a PDF or TXT file above to begin.</span>
      </div>
    );
  }

  return (
    <div className="document-list">
      <div className="doc-list-header">
        <h3>Uploaded Documents ({documents.length})</h3>
      </div>
      <div className="doc-items-container">
        {documents.map((doc) => {
          const isSelected = selectedDocId === doc.id;
          return (
            <div
              key={doc.id}
              className={`doc-card ${isSelected ? 'selected' : ''}`}
              onClick={() => onSelectDoc(doc.id)}
            >
              <div className="doc-card-main">
                <div className="doc-type-indicator">
                  <span className={`doc-tag ${doc.file_type.toLowerCase()}`}>
                    {doc.file_type}
                  </span>
                </div>
                <div className="doc-info">
                  <h4 className="doc-title" title={doc.original_name}>
                    {doc.original_name}
                  </h4>
                  <div className="doc-meta-row">
                    <span className="doc-meta-item">
                      <Calendar size={12} />
                      {formatDate(doc.uploaded_at)}
                    </span>
                    {doc.status && doc.status !== 'ready' ? (
                      <span className={`status-chip is-${doc.status}`}>
                        {doc.status === 'failed' ? 'Failed' : 'Processing…'}
                      </span>
                    ) : (
                      <span className="doc-meta-item">
                        <FileCode size={12} />
                        {(doc.text_length || 0).toLocaleString()} chars
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="doc-card-actions">
                <button
                  className="doc-delete-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (window.confirm(`Delete document "${doc.original_name}"?`)) {
                      onDeleteDoc(doc.id);
                    }
                  }}
                  title="Delete document"
                  aria-label="Delete document"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
