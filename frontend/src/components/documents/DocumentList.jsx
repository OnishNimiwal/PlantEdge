import React from 'react';
import { FileText, Trash2, Calendar, FileCode, Check } from 'lucide-react';
import { useI18n } from '../../utils/i18n';
import ClassificationChip from './ClassificationChip';

export default function DocumentList({
  documents,
  selectedDocId,
  onSelectDoc,
  onDeleteDoc,
  loading,
}) {
  const { t, lang } = useI18n();
  const formatDate = (dateStr) => {
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString(lang === 'hi' ? 'hi-IN' : [], {
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
    return <div className="doc-list-loading">{t('Loading documents…')}</div>;
  }

  if (documents.length === 0) {
    return (
      <div className="doc-list-empty">
        <FileText size={36} className="empty-docs-icon" />
        <p>{t('No documents uploaded yet.')}</p>
        <span>{t('Upload a PDF, TXT or image file above to begin.')}</span>
      </div>
    );
  }

  return (
    <div className="document-list">
      <div className="doc-list-header">
        <h3>{t('Uploaded Documents ({n})', { n: documents.length })}</h3>
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
                    <ClassificationChip level={doc.classification} source={doc.classification_source} compact />
                    {doc.status && doc.status !== 'ready' ? (
                      <span className={`status-chip is-${doc.status}`}>
                        {doc.status === 'failed' ? t('Failed') : t('Processing…')}
                      </span>
                    ) : (
                      <span className="doc-meta-item">
                        <FileCode size={12} />
                        {t('{n} chars', { n: (doc.text_length || 0).toLocaleString() })}
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
                    if (window.confirm(t('Delete document "{name}"?', { name: doc.original_name }))) {
                      onDeleteDoc(doc.id);
                    }
                  }}
                  title={t('Delete document')}
                  aria-label={t('Delete document')}
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
