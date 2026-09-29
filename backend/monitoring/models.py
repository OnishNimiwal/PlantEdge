from django.db import models


class UsageRecord(models.Model):
    """
    One row per model call (success or failure). Metadata only: no prompt,
    answer, document or image content is stored here.
    """

    CATEGORY_GENERAL = "general"
    CATEGORY_CODING = "coding"
    CATEGORY_VISION = "vision"
    CATEGORY_CHOICES = [
        (CATEGORY_GENERAL, "General"), (CATEGORY_CODING, "Coding"), (CATEGORY_VISION, "Vision"),
    ]

    model = models.CharField(max_length=100)                      # Ollama tag, e.g. qwen2.5-coder:7b
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    reason = models.CharField(max_length=40, blank=True)          # router reason, e.g. ocr_text
    source = models.CharField(max_length=20, blank=True)          # chat | document | summary
    success = models.BooleanField()
    error_type = models.CharField(max_length=40, blank=True)      # e.g. ModelTimeoutError (class name only)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    streamed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.model} {self.category} {'ok' if self.success else 'failed'}"
