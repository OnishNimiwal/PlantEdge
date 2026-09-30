"""
Usage recording and aggregation.

record() is called by the execution layer (chat/model_manager.py) for every
model call, so chat, streaming, document Q&A and summaries are all counted
exactly once. Recording never breaks a request: any database error is logged
and ignored.
"""

import logging
from datetime import datetime, time, timedelta, timezone as dt_timezone

from django.db.models import Avg, Count, Max, Q
from django.db.models.functions import TruncDate
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
            regenerated=bool(usage.get("regenerated")),
        )
    except Exception:  # never fail a user request because of analytics
        logger.exception("Could not record usage")


def record_failure(stage, source, error, reason=""):
    """
    A request that failed before any model was called (e.g. local OCR), so it is
    visible on the dashboard. Counted separately from model calls.
    """
    try:
        UsageRecord.objects.create(
            model="paddleocr" if stage == "ocr" else stage, category=UsageRecord.CATEGORY_VISION,
            reason=reason or "", source=source or "", success=False, stage=stage,
            error_type=type(error).__name__ if error is not None else "",
        )
    except Exception:
        logger.exception("Could not record failure")


TREND_DAYS = 14


def daily_trend(tz_offset_minutes=0, days=TREND_DAYS):
    """[{date, total, failed, avg_ms}] for the last `days` local days (oldest first, zero-filled)."""
    shift = timedelta(minutes=tz_offset_minutes)
    local_today = (timezone.now() - shift).date()
    first = local_today - timedelta(days=days - 1)
    start = datetime.combine(first, time.min, tzinfo=dt_timezone.utc) + shift
    rows = {}
    qs = UsageRecord.objects.filter(stage="model", created_at__gte=start).values_list(
        "created_at", "success", "duration_ms")
    for created, ok, ms in qs:  # bucket in Python: SQLite has no time-zone support
        day = (created - shift).date()
        r = rows.setdefault(day, {"total": 0, "failed": 0, "ms": []})
        r["total"] += 1
        r["failed"] += 0 if ok else 1
        if ok and ms is not None:
            r["ms"].append(ms)
    out = []
    for i in range(days):
        day = first + timedelta(days=i)
        r = rows.get(day, {"total": 0, "failed": 0, "ms": []})
        out.append({"date": day.isoformat(), "total": r["total"], "failed": r["failed"],
                    "avg_ms": round(sum(r["ms"]) / len(r["ms"])) if r["ms"] else None})
    return out


def helpfulness():
    """Per-model answer ratings from users (thumbs up / down). Not a measured accuracy."""
    from chat.models import ChatMessage

    rows = (ChatMessage.objects.filter(role="assistant").exclude(feedback="")
            .values("model").annotate(up=Count("id", filter=Q(feedback="up")),
                                      down=Count("id", filter=Q(feedback="down"))))
    return {r["model"]: {"up": r["up"], "down": r["down"]} for r in rows if r["model"]}


def summary(tz_offset_minutes=0):
    """
    Aggregated statistics. `tz_offset_minutes` is the browser's
    Date.getTimezoneOffset() (e.g. -330 for IST) so "today" is the viewer's day.
    """
    from chat.model_registry import list_models

    qs = UsageRecord.objects.filter(stage="model")
    totals = qs.aggregate(
        total=Count("id"), ok=Count("id", filter=Q(success=True)), failed=Count("id", filter=Q(success=False)),
    )
    local_now = timezone.now() - timedelta(minutes=tz_offset_minutes)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = local_midnight + timedelta(minutes=tz_offset_minutes)

    by_model = {row["model"]: row for row in qs.values("model").annotate(
        n=Count("id"), ok=Count("id", filter=Q(success=True)),
        failed=Count("id", filter=Q(success=False)), last_success=Max("created_at", filter=Q(success=True)),
        avg_ms=Avg("duration_ms", filter=Q(success=True)), regenerated=Count("id", filter=Q(regenerated=True)),
    )}
    rated = helpfulness()
    models = []
    for m in list_models():  # registered models first, always listed (zero if unused)
        row = by_model.pop(m.ollama_name, {})
        models.append({"model": m.ollama_name, "id": m.id, "name": m.name, "queries": row.get("n", 0),
                       "successful": row.get("ok", 0), "failed": row.get("failed", 0),
                       "last_success": row.get("last_success"), "avg_ms": _round(row.get("avg_ms")),
                       "regenerated": row.get("regenerated", 0),
                       "feedback": rated.get(m.ollama_name, {"up": 0, "down": 0})})
    for tag, row in by_model.items():  # models no longer in the registry
        models.append({"model": tag, "id": None, "name": tag, "queries": row["n"], "successful": row["ok"],
                       "failed": row["failed"], "last_success": row["last_success"],
                       "avg_ms": _round(row["avg_ms"]), "regenerated": row["regenerated"],
                       "feedback": rated.get(tag, {"up": 0, "down": 0})})

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
        "regenerated": qs.filter(regenerated=True).count(),
        "backfilled": qs.filter(backfilled=True).count(),
        "pre_model_failures": {row["stage"]: row["n"] for row in UsageRecord.objects.exclude(stage="model")
                               .values("stage").annotate(n=Count("id"))},
        "feedback": {"up": sum(v["up"] for v in rated.values()), "down": sum(v["down"] for v in rated.values())},
        "trend": daily_trend(tz_offset_minutes),
        "generated_at": timezone.now(),
    }


def _round(v):
    return round(v) if v is not None else None


def last_success_by_model():
    return {row["model"]: row["t"] for row in UsageRecord.objects.filter(success=True, stage="model")
            .values("model").annotate(t=Max("created_at"))}
