from django.core.management.base import BaseCommand, CommandError

from knowledge import store
from knowledge.search import search


class Command(BaseCommand):
    help = ("Hybrid (semantic + BM25) search across indexed documents in the local knowledge store. "
            "Run while the server is stopped, or use POST /api/knowledge/search/.")

    def add_arguments(self, parser):
        parser.add_argument("query")
        parser.add_argument("--doc", type=int, action="append", help="Only this document id (repeatable)")
        parser.add_argument("--limit", type=int, default=5)

    def handle(self, *args, **opts):
        try:
            hits, method = search(opts["query"], document_ids=opts["doc"], limit=opts["limit"])
        except store.StoreError as exc:
            raise CommandError(str(exc))
        finally:
            store.close()
        self.stdout.write(f"{len(hits)} result(s) ({method})")
        for h in hits:
            page = f" p.{h['page']}" if h["page"] else ""
            snippet = " ".join(h["text"].split())[:160]
            self.stdout.write(f"{h['score']:.4f}  #{h['document_id']} {h['document_name']}{page}  {snippet}")
