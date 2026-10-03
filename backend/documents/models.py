import os
from django.db import models

class Document(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_PROCESSING = "processing"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(STATUS_QUEUED, "Queued"), (STATUS_PROCESSING, "Processing"),
                      (STATUS_READY, "Ready"), (STATUS_FAILED, "Failed")]

    file = models.FileField(upload_to="documents/%Y/%m/")
    original_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=10)  # 'PDF', 'TXT', 'PNG' or 'JPG'
    extracted_text = models.TextField(blank=True)
    # 'text' (text layer / plain text), 'ocr' (local PaddleOCR) or 'text+ocr' (mixed PDF)
    extraction_method = models.CharField(max_length=10, default='text')
    ocr_pages = models.PositiveIntegerField(default=0)
    ocr_confidence = models.FloatField(null=True, blank=True)  # mean PaddleOCR recognition score
    page_count = models.PositiveIntegerField(default=0)
    ocr_pages_skipped = models.PositiveIntegerField(default=0)  # scanned pages beyond OCR_MAX_PDF_PAGES
    truncated = models.BooleanField(default=False)  # text cut at DOCUMENT_MAX_CHARS
    original_chars = models.PositiveIntegerField(default=0)
    ocr_lang = models.CharField(max_length=10, blank=True)       # PaddleOCR language used
    complex_layout = models.BooleanField(default=False)           # table / multi-column detected
    vision_fallback_pages = models.PositiveIntegerField(default=0)  # low-confidence pages re-read by the VL model
    # Background processing (documents/jobs.py)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_READY)
    progress_done = models.PositiveIntegerField(default=0)
    progress_total = models.PositiveIntegerField(default=0)
    processing_error = models.CharField(max_length=300, blank=True)
    # Character offset where each PDF page starts in extracted_text (page-level citations).
    page_offsets = models.JSONField(default=list, blank=True)
    # Local knowledge index (knowledge/indexing.py): sections embedded into Qdrant Edge.
    # index_fingerprint = retrieval.sections_fingerprint() of the text that was indexed; the
    # index is only used while it matches the current text, otherwise in-memory BM25 is used.
    INDEX_NONE = ""
    INDEX_PENDING = "pending"
    INDEX_INDEXED = "indexed"
    INDEX_FAILED = "failed"
    INDEX_STATUS_CHOICES = [(INDEX_NONE, "Not indexed"), (INDEX_PENDING, "Pending"),
                            (INDEX_INDEXED, "Indexed"), (INDEX_FAILED, "Failed")]
    index_status = models.CharField(max_length=10, choices=INDEX_STATUS_CHOICES, default=INDEX_NONE, blank=True)
    index_chunks = models.PositiveIntegerField(default=0)
    index_model = models.CharField(max_length=100, blank=True)   # embedding model used
    index_fingerprint = models.CharField(max_length=40, blank=True)
    index_error = models.CharField(max_length=300, blank=True)
    indexed_at = models.DateTimeField(null=True, blank=True)
    # Data classification (knowledge/policy.py enforces it). Only PUBLIC and SHAREABLE content
    # may ever leave this site; INTERNAL and CONFIDENTIAL stay on the edge device.
    CLASS_PUBLIC = "public"
    CLASS_SHAREABLE = "shareable"
    CLASS_INTERNAL = "internal"
    CLASS_CONFIDENTIAL = "confidential"
    CLASSIFICATION_CHOICES = [(CLASS_PUBLIC, "Public"), (CLASS_SHAREABLE, "Shareable"),
                              (CLASS_INTERNAL, "Internal"), (CLASS_CONFIDENTIAL, "Confidential")]
    SOURCE_DEFAULT = "default"     # nobody chose: settings.DEFAULT_CLASSIFICATION
    SOURCE_USER = "user"           # chosen at upload or changed later
    SOURCE_DETECTED = "detected"   # raised automatically by the content scan (knowledge/sensitivity.py)
    classification = models.CharField(max_length=12, choices=CLASSIFICATION_CHOICES, default=CLASS_INTERNAL,
                                      db_index=True)
    classification_source = models.CharField(max_length=10, default=SOURCE_DEFAULT)
    # [{"type", "label", "count", "min_level"}] found by the content scan; matched values are not stored.
    sensitivity_markers = models.JSONField(default=list, blank=True)
    classified_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.original_name} ({self.file_type}) - {self.uploaded_at.strftime('%Y-%m-%d %H:%M')}"

    def delete(self, *args, **kwargs):
        """Clean up the local physical file upon model deletion."""
        if self.file and os.path.isfile(self.file.path):
            try:
                os.remove(self.file.path)
            except OSError:
                pass
        super().delete(*args, **kwargs)
