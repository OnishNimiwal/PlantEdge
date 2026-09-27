import os
from django.db import models

class Document(models.Model):
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
