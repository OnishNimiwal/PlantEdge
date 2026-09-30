"""
Delete dashboard usage rows older than the retention period.

    python manage.py prune_usage                 # dry run, uses USAGE_RETENTION_DAYS
    python manage.py prune_usage --days 90 --apply

Only UsageRecord metadata rows are removed; conversations, documents and answer
ratings are not touched.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from monitoring.models import UsageRecord


class Command(BaseCommand):
    help = "Delete usage rows older than USAGE_RETENTION_DAYS (dry run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, help="retention in days (default: settings.USAGE_RETENTION_DAYS)")
        parser.add_argument("--apply", action="store_true", help="delete (default: dry run)")

    def handle(self, *args, days=None, apply=False, **opts):
        days = days if days is not None else getattr(settings, "USAGE_RETENTION_DAYS", 365)
        if days < 1:
            raise CommandError("Retention must be at least 1 day.")
        cutoff = timezone.now() - timedelta(days=days)
        old = UsageRecord.objects.filter(created_at__lt=cutoff)
        n = old.count()
        self.stdout.write(f"Usage rows older than {days} days ({cutoff:%Y-%m-%d}): {n}")
        if not apply:
            self.stdout.write(self.style.WARNING("Dry run - nothing deleted. Re-run with --apply to delete."))
            return
        old.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {n} usage rows."))
