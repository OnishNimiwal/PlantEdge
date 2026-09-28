import React, { useState, useRef, useEffect } from 'react';
import { UploadCloud, FileText, AlertCircle, Loader2, CheckCircle2 } from 'lucide-react';
import { uploadDocument, getOCRConfig } from '../../api/documentApi';

export default function DocumentUpload({ onUploadSuccess }) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);
  const fileInputRef = useRef(null);
  const [ocrLanguages, setOcrLanguages] = useState([]);
  const [ocrLang, setOcrLang] = useState('');

  useEffect(() => {
    getOCRConfig().then((cfg) => {
      setOcrLanguages(cfg.languages || []);
      setOcrLang(cfg.default || '');
    });
  }, []);

  const allowedExtensions = ['.pdf', '.txt', '.png', '.jpg', '.jpeg'];

  const validateFile = (file) => {
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
    if (!allowedExtensions.includes(ext)) {
      return `Invalid file type '${ext}'. Only PDF, TXT, PNG and JPG/JPEG files are supported.`;
    }
    if (file.size === 0) {
      return "The selected file is empty.";
    }
    if (file.size > 15 * 1024 * 1024) {
      return "File size exceeds 15MB limit.";
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
    try {
      const res = await uploadDocument(file, ocrLang);
      if (res && res.success) {
        const ocrPages = res.document?.ocr_pages || 0;
        setSuccessMsg(
          ocrPages
            ? `"${file.name}" processed with local OCR (${ocrPages} page${ocrPages > 1 ? 's' : ''}).`
            : `"${file.name}" uploaded and text extracted successfully!`
        );
        if (onUploadSuccess) onUploadSuccess(res.document);
        setTimeout(() => setSuccessMsg(null), 4000);
      } else {
        setError(res.error || "Failed to process document on server.");
      }
    } catch (err) {
      setError(err.message || "An error occurred during upload.");
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
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
            <ol className="upload-steps" aria-label="Processing status">
              <li className="is-done"><CheckCircle2 size={14} /> Uploaded</li>
              <li className="is-active"><Loader2 size={14} className="spin-icon" /> Processing: reading text, OCR for scanned pages</li>
              <li><span className="step-dot" /> Ready</li>
            </ol>
            <p className="upload-sub">Scanned pages take about 20 seconds each. You can keep this tab open.</p>
          </div>
        ) : (
          <div className="upload-state">
            <div className="upload-icon-wrap">
              <UploadCloud size={30} />
            </div>
            <p className="upload-title">
              <strong>Click to upload</strong> or drag & drop file here
            </p>
            <p className="upload-sub">PDF, TXT, PNG or JPG (Max 15MB) · scans are OCR'd locally</p>
          </div>
        )}
      </div>

      {ocrLanguages.length > 1 && (
        <label className="ocr-lang-row" title="Language of the text in scanned pages and images">
          <span>OCR language</span>
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
