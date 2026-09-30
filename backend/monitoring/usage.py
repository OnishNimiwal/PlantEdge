"""
Usage recording and aggregation.

record() is called by the execution layer (chat/model_manager.py) for every
model call, so chat, streaming, document Q&A and summaries are all counted
exactly once. Recording never breaks a request: any database error is logged
and ignored.
"""

import logging
from datetime import timedelta

from django.db.models import Count, Max, Q
from django.utils import timezone

from .models import UsageRecord

logger = logging.getLogger(__name__)

# Router reason -> dashboard category (General / Coding / Vision).
REASON_CATEGORY = {
    "general_reasoning": UsageRecord.CATEGORY_GENERAL,
    "ocr_text": UsageRecord.CATEGORY_GENERAL,      # OCR text answered by the text model
    "coding": UsageRecord.CATEGORY_CODING,
    "vision": UsageRecord.CATEGORY_VISION,
    "vision_ocr": UsageRecord.CATEGORY_VISION,
    "vision_coding": UsageRecord.CATEGORY_CODING,   # the vision pre-step is recorded as vision
}
CAPABILITY_CATEGORY = {
    "reasoning": UsageRecord.CATEGORY_GENERAL,
    "coding": UsageRecord.CATEGORY_CODING,
    "vision": UsageRecord.CATEGORY_VISION,
}


def category_for(reason, model):
    """Category from the routing reason; manual/unknown reasons fall back to the model's capability."""
    return REASON_CATEGORY.get(reason) or CAPABILITY_CATEGORY.get(model.capability, UsageRecord.CATEGORY_GENERAL)


def record(model, usage, success, duration_ms=None, error=None, streamed=False):
    """Store one usage row. `usage` = {"reason": ..., "source": ...} or None (then nothing is recorded)."""
    if usage is None:
        return
    try:
        UsageRecord.objects.create(
            model=model.ollama_name,
            category=category_for(usage.get("reason"), model),
            reason=usage.get("reason") or "",
            source=usage.get("source") or "",
            success=success,
            error_type=type(error).__name__ if error is not None else "",
            duration_ms=duration_ms,
            streamed=streamed,
        )
    except Exception:  # never fail a user request because of analytics
        logger.exception("Could not record usage")


def summary(tz_offset_minutes=0):
    """
    Aggregated statistics. `tz_offset_minutes` is the browser's
    Date.getTimezoneOffset() (e.g. -330 for IST) so "today" is the viewer's day.
    """
    from chat.model_registry import list_models

    qs = UsageRecord.objects.all()
    totals = qs.aggregate(
        total=Count("id"), ok=Count("id", filter=Q(success=True)), failed=Count("id", filter=Q(success=False)),
    )
    local_now = timezone.now() - timedelta(minutes=tz_offset_minutes)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = local_midnight + timedelta(minutes=tz_offset_minutes)

    by_model = {row["model"]: row for row in qs.values("model").annotate(
        n=Count("id"), ok=Count("id", filter=Q(success=True)),
        failed=Count("id", filter=Q(success=False)), last_success=Max("created_at", filter=Q(success=True)),
    )}
    models = []
    for m in list_models():  # registered models first, always listed (zero if unused)
        row = by_model.pop(m.ollama_name, {})
        models.append({"model": m.ollama_name, "id": m.id, "name": m.name, "queries": row.get("n", 0),
                       "successful": row.get("ok", 0), "failed": row.get("failed", 0),
                       "last_success": row.get("last_success")})
    for tag, row in by_model.items():  # models no longer in the registry
        models.append({"model": tag, "id": None, "name": tag, "queries": row["n"], "successful": row["ok"],
                       "failed": row["failed"], "last_success": row["last_success"]})

    routing = {key: 0 for key, _ in UsageRecord.CATEGORY_CHOICES}
    for row in qs.values("category").annotate(n=Count("id")):
        routing[row["category"]] = row["n"]
    sources = {row["source"] or "other": row["n"] for row in qs.values("source").annotate(n=Count("id"))}

    return {
        "total_queries": totals["total"],
        "successful_queries": totals["ok"],
        "failed_queries": totals["failed"],
        "today": qs.filter(created_at__gte=today_start).count(),
        "models": {m["model"]: m["queries"] for m in models},
        "model_details": models,
        "routing": routing,
        "sources": sources,
        "first_recorded": qs.order_by("created_at").values_list("created_at", flat=True).first(),
        "generated_at": timezone.now(),
    }


def last_success_by_model():
    return {row["model"]: row["t"] for row in UsageRecord.objects.filter(success=True)
            .values("model").annotate(t=Max("created_at"))}
