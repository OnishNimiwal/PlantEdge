import React, { useState, useRef } from 'react';
import { UploadCloud, FileText, AlertCircle, Loader2, CheckCircle2 } from 'lucide-react';
import { uploadDocument } from '../../api/documentApi';

export default function DocumentUpload({ onUploadSuccess }) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);
  const fileInputRef = useRef(null);

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
      const res = await uploadDocument(file);
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
            <Loader2 size={32} className="spin-icon upload-icon-spin" />
            <p className="upload-title">Extracting text (local OCR for scans & images)...</p>
            <p className="upload-sub">Scanned pages take ~25 s each with PaddleOCR on PC5</p>
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
