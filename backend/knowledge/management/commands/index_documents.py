import shutil

from django.core.management.base import BaseCommand, CommandError

from documents.models import Document
from knowledge import indexing, store


class Command(BaseCommand):
    help = ("Index ready documents into the local Qdrant Edge knowledge store (only missing / out-of-date "
            "ones unless --force). Run while the server is stopped, or use POST /api/knowledge/reindex/.")

    def add_arguments(self, parser):
        parser.add_argument("--doc", type=int, action="append", help="Only this document id (repeatable)")
        parser.add_argument("--force", action="store_true", help="Re-embed even if the index is up to date")
        parser.add_argument("--rebuild", action="store_true",
                            help="Delete the store and index every document again (e.g. after changing EMBEDDING_MODEL)")
        parser.add_argument("--prune", action="store_true", help="Only remove sections of deleted documents")

    def handle(self, *args, **opts):
        if not indexing.enabled():
            raise CommandError("KNOWLEDGE_INDEXING is off.")
        try:
            if opts["prune"]:
                self.stdout.write(f"Removed {indexing.prune_orphans()} deleted document(s) from the store.")
                return
            if opts["rebuild"]:
                self._wipe()
            ready = Document.objects.filter(status=Document.STATUS_READY).exclude(extracted_text="")
            if opts["doc"]:
                ids = list(ready.filter(id__in=opts["doc"]).values_list("id", flat=True))
            elif opts["force"] or opts["rebuild"]:
                ids = list(ready.values_list("id", flat=True))
            else:
                ids = indexing.pending_documents()
            failed = 0
            for doc_id in ids:
                result = indexing.index_document(doc_id, force=opts["force"] or opts["rebuild"] or bool(opts["doc"]))
                doc = Document.objects.get(pk=doc_id)
                failed += result == Document.INDEX_FAILED
                self.stdout.write(f"{result or '-':8} #{doc_id} {doc.original_name} "
                                  f"({doc.index_chunks} sections){' - ' + doc.index_error if doc.index_error else ''}")
            info = store.info()
        except store.StoreError as exc:
            raise CommandError(str(exc))
        finally:
            store.close()
        self.stdout.write(f"Store: {info['points']} section(s) at {info['path']} ({info.get('embedding_model')})")
        if failed:
            raise CommandError(f"{failed} document(s) could not be indexed.")
        self.stdout.write(self.style.SUCCESS(f"{len(ids)} document(s) processed."))

    def _wipe(self):
        path = store.store_dir()
        store.close()
        if path.exists():
            if not ((path / "edge_config.json").exists() or (path / store.META_FILE).exists()):
                raise CommandError(f"{path} does not look like a knowledge store; not deleting it.")
            shutil.rmtree(path)
            self.stdout.write(f"Deleted the knowledge store at {path}.")
        Document.objects.update(index_status=Document.INDEX_NONE, index_chunks=0, index_fingerprint="")
