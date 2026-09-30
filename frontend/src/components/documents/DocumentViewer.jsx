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
import Markdown from '../LazyMarkdown';
import CopyButton from '../CopyButton';
import { BasisIndicator } from '../MessageBubble';
import { modelMeta } from '../../utils/modelLabels';
import { useI18n } from '../../utils/i18n';
import { summarizeDocument, downloadDocumentReport } from '../../api/documentApi';

export default function DocumentViewer({ document, onDelete, onImageClick, conversationId, onConversationsChanged }) {
  const { t, lang } = useI18n();
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
        <h3>{t('Select a document')}</h3>
        <p>{t('Choose an uploaded file from the left panel to review its contents, ask questions, or generate a Word report.')}</p>
      </div>
    );
  }

  if (document.status && document.status !== 'ready') {
    const failed = document.status === 'failed';
    return (
      <div className="doc-viewer-empty doc-processing" role="status" aria-live="polite">
        {failed ? <AlertTriangle size={40} /> : <Loader2 size={40} className="spin-icon" />}
        <h3>{failed ? t('Processing failed') : t('Processing document…')}</h3>
        <p>
          {failed
            ? document.processing_error || t('The document could not be processed.')
            : document.progress_total
              ? t('Reading page {done} of {total}. Scanned pages take a few seconds each.', { done: Math.min(document.progress_done + 1, document.progress_total), total: document.progress_total })
              : t('Extracting text. Scanned pages are read with local OCR.')}
        </p>
        {failed && (
          <button className="action-btn danger" onClick={() => onDelete(document.id)}>
            <Trash2 size={15} /> <span>{t('Remove')}</span>
          </button>
        )}
      </div>
    );
  }

  const maxChars = document.limits?.max_chars || 50000;
  const limitWarnings = [];
  if (document.truncated) {
    limitWarnings.push(
      t('Only the first {kept} of {total} extracted characters were kept (DOCUMENT_MAX_CHARS).', { kept: maxChars.toLocaleString(), total: (document.original_chars || 0).toLocaleString() })
    );
  }
  if (document.complex_layout) {
    limitWarnings.push(
      t('Table or multi-column layout detected: tables and columns were reconstructed from the OCR layout. Check tables against the original.')
    );
  }
  if (document.ocr_pages > 0 && document.ocr_confidence != null && document.ocr_confidence < 0.85) {
    limitWarnings.push(
      t('Low OCR recognition confidence: the scan may be poor quality, rotated, handwritten or in a different language. Verify important values against the original.')
    );
  }
  if (document.vision_fallback_pages > 0) {
    limitWarnings.push(
      t('{n} page(s) had low OCR confidence (e.g. handwriting or a poor scan) and were transcribed by the vision model instead. A vision model can misread or invent text: verify against the original.', { n: document.vision_fallback_pages })
    );
  }
  if (document.ocr_pages_skipped > 0) {
    limitWarnings.push(
      t("{n} scanned page(s) were not OCR'd: the limit is {max} OCR pages per PDF (OCR_MAX_PDF_PAGES).", { n: document.ocr_pages_skipped, max: document.limits?.max_ocr_pages })
    );
  }

  const handleGenerateSummary = async () => {
    setActiveTab('summary');
    setSummaryLoading(true);
    setSummaryError(null);

    try {
      const res = await summarizeDocument(document.id, lang);
      if (res && res.success && res.summary) {
        setSummary(res.summary);
        setSummaryMeta({ model: res.ollama_model, routing: res.routing?.reason, context: res.context, basis: res.basis });
      } else {
        setSummaryError(res?.error || t('Failed to generate summary from local AI.'));
      }
    } catch (err) {
      setSummaryError(err.message || t('Error generating document summary.'));
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
        setDownloadError(res.error || t('Failed to generate Word report.'));
      }
    } catch (err) {
      setDownloadError(err.message || t('Failed to download Word report.'));
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
            <span className="status-chip is-ready" title={t('Text extracted; ready for questions and summaries')}>
              <CheckCircle2 size={12} /> {t('Ready')}
            </span>
          </div>

          <div className="doc-meta-badges">
            <span className="meta-badge">
              <Calendar size={13} />
              {new Date(document.uploaded_at).toLocaleString(lang === 'hi' ? 'hi-IN' : undefined)}
            </span>
            <span className="meta-badge">
              <Layers size={13} />
              {t('{n} chars', { n: `${(document.extracted_text || '').length.toLocaleString()} / ${maxChars.toLocaleString()}` })}
            </span>
            {document.ocr_pages > 0 && (
              <span
                className="meta-badge ocr"
                title={t("Text extracted locally with PaddleOCR. Recognition confidence is PaddleOCR's own score for the text it found; it is not a measured accuracy and can be high even when text is misread or missing.")}
              >
                <ScanText size={13} />
                OCR{document.ocr_lang ? ` (${document.ocr_lang})` : ''} · {t('{n} page(s)', { n: document.ocr_pages })}
                {document.ocr_confidence != null && ` · ${t('recognition confidence')} ${Math.round(document.ocr_confidence * 100)}%`}
              </span>
            )}
            {document.truncated && (
              <span className="meta-badge warning" title={t('Text was capped at {n} characters', { n: maxChars.toLocaleString() })}>
                <AlertTriangle size={12} /> {t('Capped at {n} chars', { n: maxChars.toLocaleString() })}
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
            title={t('Generate AI Summary')}
          >
            {summaryLoading ? <Loader2 size={15} className="spin-icon" /> : <Sparkles size={15} />}
            <span>{summary ? t('Regenerate Summary') : t('Generate Summary')}</span>
          </button>

          <button
            className="action-btn secondary"
            onClick={handleDownloadReport}
            disabled={downloadingDocx}
            title={t('Export and download Word report (.docx)')}
          >
            {downloadingDocx ? <Loader2 size={15} className="spin-icon" /> : <Download size={15} />}
            <span>{t('Export DOCX')}</span>
          </button>

          <button
            className="action-btn danger"
            onClick={() => {
              if (window.confirm(t('Are you sure you want to delete "{name}"?', { name: document.original_name }))) {
                onDelete(document.id);
              }
            }}
            title={t('Delete this document')} aria-label={t('Delete this document')}
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
          <span>{t('Document Q&A')}</span>
        </button>

        <button
          className={`tab-btn ${activeTab === 'summary' ? 'active' : ''}`}
          onClick={() => setActiveTab('summary')}
        >
          <Sparkles size={16} />
          <span>{t('AI Executive Summary')}</span>
          {summary && <span className="tab-pill">{t('Ready')}</span>}
        </button>

        <button
          className={`tab-btn ${activeTab === 'text' ? 'active' : ''}`}
          onClick={() => setActiveTab('text')}
        >
          <FileCode size={16} />
          <span>{t('Extracted Text')}</span>
        </button>
      </div>

      {/* Tab Panels */}
      <div className="doc-viewer-body">
        {activeTab === 'qa' && (
          <DocumentQuestionBox
            key={document.id}
            documentId={document.id}
            onImageClick={onImageClick}
            initialConversationId={conversationId}
            onConversationsChanged={onConversationsChanged}
            documentName={document.original_name}
          />
        )}

        {activeTab === 'summary' && (
          <div className="doc-summary-panel">
            {summaryLoading ? (
              <div className="summary-loading-state">
                <Loader2 size={32} className="spin-icon text-primary" />
                <p>{t('Generating executive summary with the local Qwen model…')}</p>
                <span>{t('Processed on this machine with no external cloud calls')}</span>
              </div>
            ) : summaryError ? (
              <div className="summary-error-state">
                <AlertTriangle size={24} />
                <p>{summaryError}</p>
                <button className="retry-btn" onClick={handleGenerateSummary}>
                  {t('Try Again')}
                </button>
              </div>
            ) : summary ? (
              <div className="summary-card">
                <div className="summary-card-header">
                  <div>
                    <h3>{t('Executive Summary')}</h3>
                    {summaryMeta?.model && (
                      <span className="msg-meta-detail">{t('MRPL Local AI')} · {modelMeta(summaryMeta.model, summaryMeta.routing, t)}</span>
                    )}
                  </div>
                  <CopyButton getText={() => summaryRef.current?.innerText?.trim() || summary} />
                </div>
                {summaryMeta?.context?.context_truncated && (
                  <span className="context-note">
                    {summaryMeta.context.retrieval
                      ? t('Long document: {used} sections spread across the document were used.', { used: summaryMeta.context.sections_used })
                      : t('The model read the first {used} of {total} characters (model context window limit).', {
                        used: summaryMeta.context.context_chars_used.toLocaleString(),
                        total: summaryMeta.context.document_chars.toLocaleString(),
                      })}
                  </span>
                )}
                <BasisIndicator basis={summaryMeta?.basis} />
                <div className="summary-content" ref={summaryRef}>
                  <Markdown text={summary} />
                </div>
              </div>
            ) : (
              <div className="summary-empty-state">
                <Sparkles size={36} className="sparkles-icon" />
                <h3>{t('No summary generated yet')}</h3>
                <p>{t('Click "Generate Summary" to have the local AI summarize this document.')}</p>
                <button className="action-btn primary" onClick={handleGenerateSummary}>
                  <Sparkles size={15} />
                  <span>{t('Generate Summary')}</span>
                </button>
              </div>
            )}
          </div>
        )}

        {activeTab === 'text' && (
          <div className="doc-text-panel">
            <div className="text-panel-header">
              <span className="text-char-info">
                {t('Raw Extracted Content ({n} characters)', { n: (document.extracted_text || '').length.toLocaleString() })}
              </span>
              <CopyButton getText={() => document.extracted_text || ''} label={t('Copy text')} />
            </div>
            <pre className="extracted-text-viewer">
              {document.extracted_text || t('No text available.')}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
