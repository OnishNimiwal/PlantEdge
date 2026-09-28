import React, { useState, useEffect } from 'react';
import DocumentUpload from './DocumentUpload';
import DocumentList from './DocumentList';
import DocumentViewer from './DocumentViewer';
import { getDocuments, getDocument, deleteDocument } from '../../api/documentApi';

export default function DocumentsPage({ onImageClick }) {
  const [documents, setDocuments] = useState([]);
  const [selectedDocId, setSelectedDocId] = useState(null);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchDocs = async () => {
    setLoading(true);
    try {
      const res = await getDocuments();
      if (res && res.success) {
        setDocuments(res.documents || []);
        // If nothing selected and documents exist, auto-select first
        if (!selectedDocId && res.documents && res.documents.length > 0) {
          handleSelectDoc(res.documents[0].id);
        }
      }
    } catch (err) {
      console.error("Failed to load documents:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocs();
  }, []);

  const handleSelectDoc = async (id) => {
    setSelectedDocId(id);
    try {
      const res = await getDocument(id);
      if (res && res.success) {
        setSelectedDoc(res.document);
      }
    } catch (err) {
      console.error("Failed to fetch document details:", err);
    }
  };

  const handleUploadSuccess = (newDoc) => {
    setDocuments((prev) => [newDoc, ...prev]);
    setSelectedDocId(newDoc.id);
    setSelectedDoc(newDoc);
  };

  const handleDeleteDoc = async (id) => {
    try {
      const res = await deleteDocument(id);
      if (res && res.success) {
        setDocuments((prev) => prev.filter((d) => d.id !== id));
        if (selectedDocId === id) {
          const remaining = documents.filter((d) => d.id !== id);
          if (remaining.length > 0) {
            handleSelectDoc(remaining[0].id);
          } else {
            setSelectedDocId(null);
            setSelectedDoc(null);
          }
        }
      }
    } catch (err) {
      console.error("Failed to delete document:", err);
    }
  };

  return (
    <div className="documents-page">
      {/* Left Sidebar / Master Panel */}
      <aside className="documents-sidebar">
        <DocumentUpload onUploadSuccess={handleUploadSuccess} />
        <DocumentList
          documents={documents}
          selectedDocId={selectedDocId}
          onSelectDoc={handleSelectDoc}
          onDeleteDoc={handleDeleteDoc}
          loading={loading}
        />
      </aside>

      {/* Right Content / Detail Panel */}
      <section className="documents-main">
        <DocumentViewer
          onImageClick={onImageClick}
          document={selectedDoc}
          onDelete={handleDeleteDoc}
        />
      </section>
    </div>
  );
}
