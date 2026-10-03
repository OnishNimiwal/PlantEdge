from django.db import models


class PolicyEvent(models.Model):
    """
    Audit trail of data-classification decisions (knowledge/policy.py). Rows are never
    edited; the document link is kept as a name when the document is deleted.
    Content is never stored here - only levels, reasons and counts.
    """

    CLASSIFIED = "classified"            # level set at upload (user choice or default)
    AUTO_ESCALATED = "auto_escalated"    # content scan raised the level
    CHANGED = "changed"                  # level changed by a user
    CHANGE_REFUSED = "change_refused"    # downgrade refused by policy
    EGRESS_ALLOWED = "egress_allowed"    # sections released by the egress guard
    EGRESS_BLOCKED = "egress_blocked"    # sections stopped by the egress guard
    EVENT_CHOICES = [(e, e.replace("_", " ").capitalize()) for e in (
        CLASSIFIED, AUTO_ESCALATED, CHANGED, CHANGE_REFUSED, EGRESS_ALLOWED, EGRESS_BLOCKED)]

    event = models.CharField(max_length=20, choices=EVENT_CHOICES, db_index=True)
    document = models.ForeignKey("documents.Document", null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="policy_events")
    document_name = models.CharField(max_length=255, blank=True)
    from_level = models.CharField(max_length=12, blank=True)
    to_level = models.CharField(max_length=12, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    client = models.CharField(max_length=64, blank=True)   # requesting address (no user accounts yet)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.event} {self.document_name}"
