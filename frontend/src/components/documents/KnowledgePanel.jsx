import React, { useEffect, useState } from 'react';
import { Library, Database, AlertTriangle } from 'lucide-react';
import { useI18n } from '../../utils/i18n';
import DocumentQuestionBox from './DocumentQuestionBox';
import { getKnowledgeStatus, getLatestKnowledgeConversation, streamKnowledgeQuestion } from '../../api/knowledgeApi';

/** Q&A across every indexed document (local Qdrant Edge knowledge base). */
export default function KnowledgePanel({ onImageClick, onConversationsChanged, refreshKey }) {
  const { t } = useI18n();
  const [status, setStatus] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getKnowledgeStatus().then((s) => { if (!cancelled) setStatus(s); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  const docs = status?.documents;
  const needs = docs?.needs_indexing || 0;

  return (
    <div className="document-viewer">
      <div className="doc-viewer-header">
        <div className="doc-viewer-meta-main">
          <div className="doc-title-row">
            <Library size={20} aria-hidden="true" />
            <h2 className="doc-header-title">{t('Knowledge base')}</h2>
          </div>
          <div className="doc-meta-badges">
            {docs && (
              <span className="meta-badge" title={t('Documents whose sections are in the local knowledge store')}>
                <Database size={13} />
                {t('{indexed} of {ready} documents indexed', { indexed: docs.indexed, ready: docs.ready })}
                {status.store?.points ? ` · ${t('{n} sections', { n: status.store.points })}` : ''}
              </span>
            )}
            {needs > 0 && (
              <span className="meta-badge warning" title={t('These documents are answered with keyword search until they are indexed.')}>
                <AlertTriangle size={12} /> {t('{n} document(s) waiting for indexing', { n: needs })}
              </span>
            )}
            {status?.store?.state === 'unavailable' && (
              <span className="meta-badge warning" title={status.store.reason}>
                <AlertTriangle size={12} /> {t('Knowledge store unavailable')}
              </span>
            )}
          </div>
        </div>
      </div>
      <div className="doc-viewer-body">
        <DocumentQuestionBox
          key="knowledge"
          documentId="knowledge"
          onImageClick={onImageClick}
          onConversationsChanged={onConversationsChanged}
          streamQuestion={streamKnowledgeQuestion}
          loadLatest={getLatestKnowledgeConversation}
          emptyTitle={t('Ask a question across all site documents')}
          emptyHint={t('The most relevant sections of every indexed document are found by meaning, not only by keywords. Answers cite their sources as [S1], [S2] …')}
          placeholder={t('Ask the knowledge base…')}
          footnote={t('Answers are generated locally from the indexed documents. Check the cited sources.')}
          newTitle={t('Start a new knowledge base conversation')}
        />
      </div>
    </div>
  );
}
