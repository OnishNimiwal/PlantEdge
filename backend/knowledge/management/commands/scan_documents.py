from django.core.management.base import BaseCommand

from documents.models import Document
from knowledge import policy, sensitivity


class Command(BaseCommand):
    help = ("Run the sensitive-content scan on ready documents (e.g. ones uploaded before classification "
            "existed). It can only raise a classification; every change is written to the audit log.")

    def handle(self, *args, **opts):
        for doc in Document.objects.filter(status=Document.STATUS_READY).order_by("id"):
            before = doc.classification
            markers = policy.apply_content_scan(doc)
            change = f"{before} -> {doc.classification}" if doc.classification != before else doc.classification
            found = sensitivity.summary(markers) or "nothing found"
            self.stdout.write(f"#{doc.id} {doc.original_name}: {change} ({found})")
