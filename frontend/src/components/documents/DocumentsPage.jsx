import React, { useState, useEffect, useCallback } from 'react';
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import DocumentUpload from './DocumentUpload';
import DocumentList from './DocumentList';
import DocumentViewer from './DocumentViewer';
import { getDocuments, getDocument, deleteDocument } from '../../api/documentApi';

const COMPACT_QUERY = '(max-width: 1280px)';

export default function DocumentsPage({ onImageClick, openRequest, onConversationsChanged }) {
  const [documents, setDocuments] = useState([]);
  const [selectedDocId, setSelectedDocId] = useState(null);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [loading, setLoading] = useState(true);
  const [requestedConversation, setRequestedConversation] = useState(null);
  // The document list collapses on medium screens once a document is open.
  const [panelOpen, setPanelOpen] = useState(true);

  const handleSelectDoc = useCallback(async (id, conversationId = null) => {
    setSelectedDocId(id);
    setRequestedConversation(conversationId);
    try {
      const res = await getDocument(id);
      if (res && res.success) {
        setSelectedDoc(res.document);
        if (window.matchMedia?.(COMPACT_QUERY).matches) setPanelOpen(false);
      }
    } catch (err) {
      console.warn('Failed to fetch document details:', err);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      const res = await getDocuments();
      if (cancelled) return;
      setLoading(false);
      if (res && res.success) {
        setDocuments(res.documents || []);
        if (!openRequest && res.documents?.length) handleSelectDoc(res.documents[0].id);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Opened from the sidebar: show that document and that Q&A conversation.
  useEffect(() => {
    if (openRequest?.documentId) handleSelectDoc(openRequest.documentId, openRequest.conversationId);
  }, [openRequest, handleSelectDoc]);

  const handleUploadSuccess = (newDoc) => {
    setDocuments((prev) => [newDoc, ...prev]);
    setSelectedDocId(newDoc.id);
    setSelectedDoc(newDoc);
    setRequestedConversation(null);
  };

  const handleDeleteDoc = async (id) => {
    const res = await deleteDocument(id);
    if (res && res.success) {
      const remaining = documents.filter((d) => d.id !== id);
      setDocuments(remaining);
      onConversationsChanged?.();
      if (selectedDocId === id) {
        if (remaining.length > 0) handleSelectDoc(remaining[0].id);
        else {
          setSelectedDocId(null);
          setSelectedDoc(null);
        }
      }
    }
  };

  return (
    <div className={`documents-page ${panelOpen ? '' : 'panel-collapsed'}`}>
      <aside className="documents-sidebar" aria-label="Documents" hidden={!panelOpen}>
        <DocumentUpload onUploadSuccess={handleUploadSuccess} />
        <DocumentList
          documents={documents}
          selectedDocId={selectedDocId}
          onSelectDoc={(id) => handleSelectDoc(id)}
          onDeleteDoc={handleDeleteDoc}
          loading={loading}
        />
      </aside>

      <section className="documents-main">
        <button
          type="button"
          className="icon-btn documents-panel-toggle"
          onClick={() => setPanelOpen((v) => !v)}
          title={panelOpen ? 'Hide document list' : 'Show document list'}
          aria-label={panelOpen ? 'Hide document list' : 'Show document list'}
          aria-expanded={panelOpen}
        >
          {panelOpen ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />}
        </button>
        <DocumentViewer
          key={`${selectedDoc?.id}-${requestedConversation || ''}`}
          document={selectedDoc}
          onDelete={handleDeleteDoc}
          onImageClick={onImageClick}
          conversationId={requestedConversation}
          onConversationsChanged={onConversationsChanged}
        />
      </section>
    </div>
  );
}
