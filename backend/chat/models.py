"""
Conversation state (backend is the source of truth; the browser only keeps the id).

Conversation -> ChatMessage (user / assistant turns) -> ChatAttachment (images).
A conversation may be linked to a Document for Document Assistant Q&A.
"""

import os
import uuid

from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200, blank=True)
    document = models.ForeignKey(
        "documents.Document", null=True, blank=True, on_delete=models.CASCADE,
        related_name="conversations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or str(self.id)


class ChatMessage(models.Model):
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = [(ROLE_USER, "User"), (ROLE_ASSISTANT, "Assistant")]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    model = models.CharField(max_length=100, blank=True)          # Ollama tag that answered
    routing_reason = models.CharField(max_length=40, blank=True)  # coding | vision | ...
    # Model-only context stored with a user turn (e.g. OCR text of its images);
    # sent to models with the history, not shown in the UI.
    extra_context = models.TextField(blank=True)
    # What an assistant answer was based on (see chat/reliability.py): document | image |
    # image_text | general | code. Derived from the inputs, not a correctness guarantee.
    basis = models.CharField(max_length=20, blank=True)
    basis_detail = models.CharField(max_length=255, blank=True)
    basis_undetermined = models.BooleanField(default=False)
    basis_warnings = models.JSONField(default=list, blank=True)  # deterministic check results
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class ChatAttachment(models.Model):
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="chat/%Y/%m/")
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)


@receiver(post_delete, sender=ChatAttachment)
def _remove_attachment_file(sender, instance, **kwargs):
    """Cascade deletes do not call Model.delete(), so clean up stored images here."""
    if instance.file and os.path.isfile(instance.file.path):
        try:
            os.remove(instance.file.path)
        except OSError:
            pass
