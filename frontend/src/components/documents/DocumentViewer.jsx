import React, { useRef, useState } from 'react';
import {
  FileText,
  Sparkles,
  Download,
  Trash2,
  Calendar,
  Layers,
  MessageSquare,
  FileCode,
  Loader2,
  AlertTriangle,
  ScanText,
  CheckCircle2,
} from 'lucide-react';
import DocumentQuestionBox from './DocumentQuestionBox';
import Markdown from '../Markdown';
import CopyButton from '../CopyButton';
import { modelMeta } from '../../utils/modelLabels';
import { summarizeDocument, downloadDocumentReport } from '../../api/documentApi';

export default function DocumentViewer({ document, onDelete, onImageClick }) {
  const [activeTab, setActiveTab] = useState('qa'); // 'qa' | 'summary' | 'text'
  const [summary, setSummary] = useState(null);
  const [summaryMeta, setSummaryMeta] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState(null);

  const [downloadingDocx, setDownloadingDocx] = useState(false);
  const [downloadError, setDownloadError] = useState(null);

  const summaryRef = useRef(null);

  if (!document) {
    return (
      <div className="doc-viewer-empty">
        <FileText size={48} className="empty-icon-subtle" />
        <h3>Select a document</h3>
        <p>Choose an uploaded file from the left panel to review its contents, ask questions, or generate a Word report.</p>
      </div>
    );
  }

  const maxChars = document.limits?.max_chars || 50000;
  const limitWarnings = [];
  if (document.truncated) {
    limitWarnings.push(
      `Only the first ${maxChars.toLocaleString()} of ${(document.original_chars || 0).toLocaleString()} extracted characters were kept (DOCUMENT_MAX_CHARS).`
    );
  }
  if (document.complex_layout) {
    limitWarnings.push(
      'Table or multi-column layout detected: extracted text is flattened line by line, so columns may be interleaved. Check tables against the original.'
    );
  }
  if (document.ocr_pages > 0 && document.ocr_confidence != null && document.ocr_confidence < 0.85) {
    limitWarnings.push(
      'Low OCR recognition confidence: the scan may be poor quality, rotated, handwritten or in a different language. Verify important values against the original.'
    );
  }
  if (document.ocr_pages_skipped > 0) {
    limitWarnings.push(
      `${document.ocr_pages_skipped} scanned page(s) were not OCR'd: the limit is ${document.limits?.max_ocr_pages} OCR pages per PDF (OCR_MAX_PDF_PAGES).`
    );
  }

  const handleGenerateSummary = async () => {
    setActiveTab('summary');
    setSummaryLoading(true);
    setSummaryError(null);

    try {
      const res = await summarizeDocument(document.id);
      if (res && res.success && res.summary) {
        setSummary(res.summary);
        setSummaryMeta({ model: res.ollama_model, routing: res.routing?.reason, context: res.context });
      } else {
        setSummaryError(res?.error || "Failed to generate summary from local AI.");
      }
    } catch (err) {
      setSummaryError(err.message || "Error generating document summary.");
    } finally {
      setSummaryLoading(false);
    }
  };

  const handleDownloadReport = async () => {
    setDownloadingDocx(true);
    setDownloadError(null);

    try {
      const baseName = document.original_name.replace(/\.[^/.]+$/, "");
      const filename = `${baseName}_MRPL_Report.docx`;
      const res = await downloadDocumentReport(document.id, summary || "", filename);
      if (!res.success) {
        setDownloadError(res.error || "Failed to generate Word report.");
      }
    } catch (err) {
      setDownloadError(err.message || "Failed to download Word report.");
    } finally {
      setDownloadingDocx(false);
    }
  };

  return (
    <div className="document-viewer">
      {/* Document Top Bar */}
      <div className="doc-viewer-header">
        <div className="doc-viewer-meta-main">
          <div className="doc-title-row">
            <span className={`doc-tag ${document.file_type.toLowerCase()}`}>
              {document.file_type}
            </span>
            <h2 className="doc-header-title">{document.original_name}</h2>
            <span className="status-chip is-ready" title="Text extracted; ready for questions and summaries">
              <CheckCircle2 size={12} /> Ready
            </span>
          </div>

          <div className="doc-meta-badges">
            <span className="meta-badge">
              <Calendar size={13} />
              {new Date(document.uploaded_at).toLocaleString()}
            </span>
            <span className="meta-badge">
              <Layers size={13} />
              {(document.extracted_text || "").length.toLocaleString()} / {maxChars.toLocaleString()} chars
            </span>
            {document.ocr_pages > 0 && (
              <span
                className="meta-badge ocr"
                title="Text extracted locally with PaddleOCR. Recognition confidence is PaddleOCR's own score for the text it found; it is not a measured accuracy and can be high even when text is misread or missing."
              >
                <ScanText size={13} />
                OCR{document.ocr_lang ? ` (${document.ocr_lang})` : ''} · {document.ocr_pages} page{document.ocr_pages > 1 ? 's' : ''}
                {document.ocr_confidence != null && ` · recognition confidence ${Math.round(document.ocr_confidence * 100)}%`}
              </span>
            )}
            {document.truncated && (
              <span className="meta-badge warning" title={`Text was capped at ${maxChars.toLocaleString()} characters`}>
                <AlertTriangle size={12} /> Capped at {maxChars.toLocaleString()} chars
              </span>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="doc-viewer-actions">
          <button
            className="action-btn primary"
            onClick={handleGenerateSummary}
            disabled={summaryLoading}
            title="Generate AI Summary"
          >
            {summaryLoading ? <Loader2 size={15} className="spin-icon" /> : <Sparkles size={15} />}
            <span>{summary ? 'Regenerate Summary' : 'Generate Summary'}</span>
          </button>

          <button
            className="action-btn secondary"
            onClick={handleDownloadReport}
            disabled={downloadingDocx}
            title="Export and download Word report (.docx)"
          >
            {downloadingDocx ? <Loader2 size={15} className="spin-icon" /> : <Download size={15} />}
            <span>Export DOCX</span>
          </button>

          <button
            className="action-btn danger"
            onClick={() => {
              if (window.confirm(`Are you sure you want to delete "${document.original_name}"?`)) {
                onDelete(document.id);
              }
            }}
            title="Delete this document"
          >
            <Trash2 size={15} />
          </button>
        </div>
      </div>

      {limitWarnings.length > 0 && (
        <div className="doc-limit-banner">
          <AlertTriangle size={14} />
          <div>{limitWarnings.map((w, i) => <div key={i}>{w}</div>)}</div>
        </div>
      )}

      {downloadError && (
        <div className="download-error-bar">
          <AlertTriangle size={14} />
          <span>{downloadError}</span>
        </div>
      )}

      {/* Navigation Sub-Tabs */}
      <div className="doc-viewer-tabs">
        <button
          className={`tab-btn ${activeTab === 'qa' ? 'active' : ''}`}
          onClick={() => setActiveTab('qa')}
        >
          <MessageSquare size={16} />
          <span>Document Q&A</span>
        </button>

        <button
          className={`tab-btn ${activeTab === 'summary' ? 'active' : ''}`}
          onClick={() => setActiveTab('summary')}
        >
          <Sparkles size={16} />
          <span>AI Executive Summary</span>
          {summary && <span className="tab-pill">Ready</span>}
        </button>

        <button
          className={`tab-btn ${activeTab === 'text' ? 'active' : ''}`}
          onClick={() => setActiveTab('text')}
        >
          <FileCode size={16} />
          <span>Extracted Text</span>
        </button>
      </div>

      {/* Tab Panels */}
      <div className="doc-viewer-body">
        {activeTab === 'qa' && (
          <DocumentQuestionBox
            key={document.id}
            documentId={document.id}
            onImageClick={onImageClick}
            documentName={document.original_name}
          />
        )}

        {activeTab === 'summary' && (
          <div className="doc-summary-panel">
            {summaryLoading ? (
              <div className="summary-loading-state">
                <Loader2 size={32} className="spin-icon text-primary" />
                <p>Generating executive summary with local Qwen model...</p>
                <span>Processing on PC5 with zero external cloud calls</span>
              </div>
            ) : summaryError ? (
              <div className="summary-error-state">
                <AlertTriangle size={24} />
                <p>{summaryError}</p>
                <button className="retry-btn" onClick={handleGenerateSummary}>
                  Try Again
                </button>
              </div>
            ) : summary ? (
              <div className="summary-card">
                <div className="summary-card-header">
                  <div>
                    <h3>Executive Summary</h3>
                    {summaryMeta?.model && (
                      <span className="msg-meta-detail">MRPL Local AI · {modelMeta(summaryMeta.model, summaryMeta.routing)}</span>
                    )}
                  </div>
                  <CopyButton getText={() => summaryRef.current?.innerText?.trim() || summary} label="Copy" />
                </div>
                {summaryMeta?.context?.context_truncated && (
                  <span className="context-note">
                    The model read the first {summaryMeta.context.context_chars_used.toLocaleString()} of{' '}
                    {summaryMeta.context.document_chars.toLocaleString()} characters (model context window limit).
                  </span>
                )}
                <div className="summary-content" ref={summaryRef}>
                  <Markdown text={summary} />
                </div>
              </div>
            ) : (
              <div className="summary-empty-state">
                <Sparkles size={36} className="sparkles-icon" />
                <h3>No summary generated yet</h3>
                <p>Click "Generate Summary" to have the local AI summarize this document.</p>
                <button className="action-btn primary" onClick={handleGenerateSummary}>
                  <Sparkles size={15} />
                  <span>Generate Summary</span>
                </button>
              </div>
            )}
          </div>
        )}

        {activeTab === 'text' && (
          <div className="doc-text-panel">
            <div className="text-panel-header">
              <span className="text-char-info">
                Raw Extracted Content ({(document.extracted_text || "").length.toLocaleString()} characters)
              </span>
              <CopyButton getText={() => document.extracted_text || ''} label="Copy text" />
            </div>
            <pre className="extracted-text-viewer">
              {document.extracted_text || "No text available."}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
