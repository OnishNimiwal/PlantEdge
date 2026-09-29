from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from chat.models import Conversation
from documents.models import Document


class Command(BaseCommand):
    help = (
        "Delete development/test documents or chat conversations (database rows AND stored files). "
        "Dry run by default: nothing is deleted unless --yes is given."
    )

    def add_arguments(self, parser):
        parser.add_argument("--name", help="Only documents whose filename contains this text")
        parser.add_argument("--ids", help="Comma-separated document ids, e.g. 3,4")
        parser.add_argument("--older-than", type=int, metavar="DAYS",
                            help="Only documents uploaded more than DAYS days ago")
        parser.add_argument("--all", action="store_true",
                            help="Select every document (required when no other filter is given)")
        parser.add_argument("--conversations", action="store_true",
                            help="Clean up chat conversations (and their images) instead of documents; "
                                 "supports --older-than, --ids (UUIDs) and --all")
        parser.add_argument("--usage", action="store_true",
                            help="Reset dashboard usage records (metadata only); supports --older-than and --all")
        parser.add_argument("--yes", action="store_true", help="Actually delete (otherwise dry run)")

    def handle(self, *args, **opts):
        if opts["conversations"]:
            return self._conversations(opts)
        if opts["usage"]:
            return self._usage(opts)
        qs = Document.objects.all()
        if not (opts["name"] or opts["ids"] or opts["older_than"] is not None or opts["all"]):
            raise CommandError("Give a filter (--name, --ids, --older-than) or --all.")
        if opts["name"]:
            qs = qs.filter(original_name__icontains=opts["name"])
        if opts["ids"]:
            try:
                qs = qs.filter(id__in=[int(i) for i in opts["ids"].split(",") if i.strip()])
            except ValueError:
                raise CommandError("--ids must be comma-separated integers")
        if opts["older_than"] is not None:
            qs = qs.filter(uploaded_at__lt=timezone.now() - timedelta(days=opts["older_than"]))

        docs = list(qs.order_by("id"))
        if not docs:
            self.stdout.write("No matching documents.")
            return
        for doc in docs:
            self.stdout.write(
                f"  id={doc.id:<4} {doc.file_type:<4} {doc.uploaded_at:%Y-%m-%d %H:%M}  {doc.original_name}"
            )
        if not opts["yes"]:
            self.stdout.write(self.style.WARNING(
                f"Dry run: {len(docs)} document(s) would be deleted. Re-run with --yes to delete."
            ))
            return
        for doc in docs:
            doc.delete()  # Document.delete() also removes the stored file
        self.stdout.write(self.style.SUCCESS(f"Deleted {len(docs)} document(s)."))

    def _conversations(self, opts):
        if not (opts["ids"] or opts["older_than"] is not None or opts["all"]):
            raise CommandError("Give --ids, --older-than or --all together with --conversations.")
        qs = Conversation.objects.all()
        if opts["ids"]:
            qs = qs.filter(id__in=[i.strip() for i in opts["ids"].split(",") if i.strip()])
        if opts["older_than"] is not None:
            qs = qs.filter(updated_at__lt=timezone.now() - timedelta(days=opts["older_than"]))
        convs = list(qs)
        if not convs:
            self.stdout.write("No matching conversations.")
            return
        for c in convs:
            self.stdout.write(f"  {c.id}  {c.updated_at:%Y-%m-%d %H:%M}  msgs={c.messages.count():<3} {c.title[:60]}")
        if not opts["yes"]:
            self.stdout.write(self.style.WARNING(
                f"Dry run: {len(convs)} conversation(s) would be deleted. Re-run with --yes to delete."
            ))
            return
        for c in convs:
            c.delete()  # cascades to messages and attachments (image files removed by signal)
        self.stdout.write(self.style.SUCCESS(f"Deleted {len(convs)} conversation(s)."))

    def _usage(self, opts):
        from monitoring.models import UsageRecord
        if not (opts["older_than"] is not None or opts["all"]):
            raise CommandError("Give --older-than or --all together with --usage.")
        qs = UsageRecord.objects.all()
        if opts["older_than"] is not None:
            qs = qs.filter(created_at__lt=timezone.now() - timedelta(days=opts["older_than"]))
        count = qs.count()
        if not opts["yes"]:
            self.stdout.write(self.style.WARNING(
                f"Dry run: {count} usage record(s) would be deleted. Re-run with --yes to delete."
            ))
            return
        qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} usage record(s)."))
