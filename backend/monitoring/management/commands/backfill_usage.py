"""
Reconstruct dashboard data for answers stored before usage recording existed.

    python manage.py backfill_usage            # dry run: shows what would change
    python manage.py backfill_usage --apply    # write it

1. Usage rows: one per stored assistant answer that is older than the first recorded
   usage row (answers after that point are already counted). Rows are marked
   backfilled=True; duration is unknown and left empty. Failed calls were never stored
   as messages, so they cannot be reconstructed.
2. Basis: answers without a basis get one from what is known about the turn (document
   conversation, attached image, stored OCR text, routing reason).

Message content is only read to detect "not found" answers; nothing is logged.
Running it again is safe: answers already backfilled are skipped.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from chat import reliability
from chat.models import ChatMessage
from chat.model_registry import list_models
from monitoring.models import UsageRecord
from monitoring.usage import category_for

REASON_SOURCE_DEFAULT = "chat"


class _Model:
    """Registry model stand-in for tags that are no longer registered."""
    capability = None


def _basis_kind(msg, prev_user):
    if msg.conversation.document_id:
        return "document"
    if prev_user is not None and prev_user.attachments.exists() and msg.routing_reason in ("vision", "vision_ocr"):
        return "image"
    if prev_user is not None and prev_user.extra_context:
        return "image_text"
    return reliability.chat_basis_kind(msg.routing_reason, False, False)


class Command(BaseCommand):
    help = "Backfill usage rows and answer basis for messages stored before monitoring existed (dry run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")

    def handle(self, *args, apply=False, **opts):
        models = {m.ollama_name: m for m in list_models()}
        first_real = (UsageRecord.objects.filter(backfilled=False, stage="model")
                      .order_by("created_at").values_list("created_at", flat=True).first())
        last_backfilled = (UsageRecord.objects.filter(backfilled=True)
                           .order_by("-created_at").values_list("created_at", flat=True).first())

        answers = (ChatMessage.objects.filter(role=ChatMessage.ROLE_ASSISTANT).exclude(model="")
                   .select_related("conversation").order_by("created_at"))
        usage_rows, basis_updates = [], []
        for msg in answers.iterator():
            prev_user = None
            needs_usage = (first_real is None or msg.created_at < first_real) and \
                (last_backfilled is None or msg.created_at > last_backfilled)
            needs_basis = not msg.basis
            if not (needs_usage or needs_basis):
                continue
            prev_user = (ChatMessage.objects.filter(conversation_id=msg.conversation_id, role=ChatMessage.ROLE_USER,
                                                    created_at__lte=msg.created_at).order_by("-created_at").first())
            if needs_usage:
                source = "document" if msg.conversation.document_id else REASON_SOURCE_DEFAULT
                usage_rows.append(UsageRecord(
                    model=msg.model, category=category_for(msg.routing_reason, models.get(msg.model, _Model())),
                    reason=msg.routing_reason, source=source, success=True, backfilled=True,
                ))
                usage_rows[-1]._created = msg.created_at
            if needs_basis:
                b = reliability.basis(_basis_kind(msg, prev_user), msg.content)
                basis_updates.append((msg.id, b["type"], b["undetermined"]))

        self.stdout.write(f"Usage rows to add:   {len(usage_rows)}"
                          + (f" (answers before {first_real:%Y-%m-%d %H:%M})" if first_real else ""))
        self.stdout.write(f"Answers to label:    {len(basis_updates)}")
        kinds = {}
        for _, kind, _u in basis_updates:
            kinds[kind] = kinds.get(kind, 0) + 1
        for kind, n in sorted(kinds.items()):
            self.stdout.write(f"  basis {kind}: {n}")
        if not apply:
            self.stdout.write(self.style.WARNING("Dry run - nothing written. Re-run with --apply to write."))
            return
        with transaction.atomic():
            for row in usage_rows:
                created = row._created
                row.save()
                UsageRecord.objects.filter(pk=row.pk).update(created_at=created)  # keep the original time
            for pk, kind, undetermined in basis_updates:
                ChatMessage.objects.filter(pk=pk).update(basis=kind, basis_undetermined=undetermined)
        self.stdout.write(self.style.SUCCESS(f"Added {len(usage_rows)} usage rows, labelled {len(basis_updates)} answers."))
