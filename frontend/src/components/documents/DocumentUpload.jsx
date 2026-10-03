import React, { useState, useRef, useEffect } from 'react';
import { UploadCloud, FileText, AlertCircle, Loader2, CheckCircle2 } from 'lucide-react';
import { useI18n } from '../../utils/i18n';
import { uploadDocument, getOCRConfig, getDocument } from '../../api/documentApi';
import { getPolicy } from '../../api/knowledgeApi';
import { CLASSIFICATION_LABELS } from './ClassificationChip';

const POLL_MS = 1500;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export default function DocumentUpload({ onUploadSuccess }) {
  const { t } = useI18n();
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);
  const fileInputRef = useRef(null);
  const [ocrLanguages, setOcrLanguages] = useState([]);
  const [ocrLang, setOcrLang] = useState('');
  const [progress, setProgress] = useState(0); // transfer fraction 0..1
  const [pages, setPages] = useState(null);     // {done, total} while the server extracts text
  const [levels, setLevels] = useState([]);
  const [classification, setClassificationChoice] = useState('');

  useEffect(() => {
    getPolicy().then((p) => {
      setLevels(p.levels || []);
      setClassificationChoice(p.default || 'internal');
    });
    getOCRConfig().then((cfg) => {
      setOcrLanguages(cfg.languages || []);
      setOcrLang(cfg.default || '');
    });
  }, []);

  const allowedExtensions = ['.pdf', '.txt', '.png', '.jpg', '.jpeg'];

  const validateFile = (file) => {
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
    if (!allowedExtensions.includes(ext)) {
      return t("Invalid file type '{ext}'. Only PDF, TXT, PNG and JPG/JPEG files are supported.", { ext });
    }
    if (file.size === 0) {
      return t('The selected file is empty.');
    }
    if (file.size > 15 * 1024 * 1024) {
      return t('File size exceeds 15MB limit.');
    }
    return null;
  };

  const handleProcessFile = async (file) => {
    setError(null);
    setSuccessMsg(null);

    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsUploading(true);
    setProgress(0);
    setPages(null);
    try {
      let res = await uploadDocument(file, ocrLang, setProgress, classification);
      let doc = res?.document;
      // 202: text extraction / OCR runs in the background - poll until ready or failed.
      while (res?.success && doc && doc.status && !['ready', 'failed'].includes(doc.status)) {
        setPages({ done: doc.progress_done || 0, total: doc.progress_total || 0 });
        await sleep(POLL_MS);
        const next = await getDocument(doc.id);
        if (next?.success) doc = next.document;
      }
      if (res?.success && doc?.status !== 'failed') {
        const ocrPages = doc?.ocr_pages || 0;
        const raised = doc?.classification_source === 'detected';
        setSuccessMsg(
          (ocrPages
            ? t('"{name}" processed with local OCR ({n} page(s)).', { name: file.name, n: ocrPages })
            : t('"{name}" uploaded and text extracted successfully!', { name: file.name }))
          + (raised ? ` ${t('Classified {level}: sensitive content was found.', { level: t(CLASSIFICATION_LABELS[doc.classification]) })}` : '')
        );
        if (onUploadSuccess) onUploadSuccess(doc);
        setTimeout(() => setSuccessMsg(null), 4000);
      } else {
        setError(doc?.processing_error || res?.error || t('Failed to process document on server.'));
      }
    } catch (err) {
      setError(err.message || t('An error occurred during upload.'));
    } finally {
      setIsUploading(false);
      setPages(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleProcessFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileSelect = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleProcessFile(e.target.files[0]);
    }
  };

  return (
    <div className="document-upload-card">
      <div
        className={`dropzone ${isDragging ? 'dragging' : ''} ${isUploading ? 'uploading' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => !isUploading && fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.txt,.png,.jpg,.jpeg"
          onChange={handleFileSelect}
          style={{ display: 'none' }}
          disabled={isUploading}
        />

        {isUploading ? (
          <div className="upload-state">
            <ol className="upload-steps" aria-label={t('Processing status')} aria-live="polite">
              {progress < 1 ? (
                <li className="is-active">
                  <Loader2 size={14} className="spin-icon" /> {t('Uploading {pct}%', { pct: Math.round(progress * 100) })}
                </li>
              ) : (
                <li className="is-done"><CheckCircle2 size={14} /> {t('Uploaded')}</li>
              )}
              <li className={progress >= 1 ? 'is-active' : ''}>
                {progress >= 1 ? <Loader2 size={14} className="spin-icon" /> : <span className="step-dot" />}
                {pages?.total
                  ? t('Processing page {done} of {total}', { done: Math.min(pages.done + 1, pages.total), total: pages.total })
                  : t('Processing: reading text, OCR for scanned pages')}
              </li>
              <li><span className="step-dot" /> {t('Ready')}</li>
            </ol>
            <div
              className="upload-progress"
              role="progressbar"
              aria-label={t('Upload progress')}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progress * 100)}
            >
              <span style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
            <p className="upload-sub">{t('Scanned pages take about 10–20 seconds each to process.')}</p>
          </div>
        ) : (
          <div className="upload-state">
            <div className="upload-icon-wrap">
              <UploadCloud size={30} />
            </div>
            <p className="upload-title">
              <strong>{t('Click to upload')}</strong> {t('or drag & drop file here')}
            </p>
            <p className="upload-sub">{t("PDF, TXT, PNG or JPG (Max 15MB) · scans are OCR'd locally")}</p>
          </div>
        )}
      </div>

      {ocrLanguages.length > 1 && (
        <label className="ocr-lang-row" title={t('Language of the text in scanned pages and images')}>
          <span>{t('OCR language')}</span>
          <select
            className="model-select"
            value={ocrLang}
            onChange={(e) => setOcrLang(e.target.value)}
            disabled={isUploading}
          >
            {ocrLanguages.map((l) => (
              <option key={l.code} value={l.code}>{l.name}</option>
            ))}
          </select>
        </label>
      )}

      {levels.length > 0 && (
        <label className="ocr-lang-row" title={t('Only Public and Shareable documents may ever leave this site. The content scan can raise this level.')}>
          <span>{t('Classification')}</span>
          <select
            className="model-select"
            value={classification}
            onChange={(e) => setClassificationChoice(e.target.value)}
            disabled={isUploading}
          >
            {levels.map((l) => (
              <option key={l.id} value={l.id}>
                {t(CLASSIFICATION_LABELS[l.id] || l.id)}{l.may_leave_site ? '' : ` · ${t('stays on site')}`}
              </option>
            ))}
          </select>
        </label>
      )}

      {error && (
        <div className="upload-alert error">
          <AlertCircle size={16} className="alert-icon" />
          <span>{error}</span>
        </div>
      )}

      {successMsg && (
        <div className="upload-alert success">
          <CheckCircle2 size={16} className="alert-icon" />
          <span>{successMsg}</span>
        </div>
      )}
    </div>
  );
}
