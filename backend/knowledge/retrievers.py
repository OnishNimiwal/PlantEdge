"""
Rankers for documents/retrieval.build_context() backed by the local knowledge store.

QdrantHybridRanker orders a document's sections by hybrid (semantic + BM25)
relevance from Qdrant Edge. It is used only when the document's index matches
its current text; otherwise, or when the embedding model / store fails, it falls
back to the in-memory Bm25Ranker so a question is always answered.
"""

import logging

from django.conf import settings

from documents.models import Document
from documents.retrieval import Bm25Ranker, sections_fingerprint

from . import embeddings, indexing, store

logger = logging.getLogger(__name__)


def index_usable(document):
    return (indexing.enabled()
            and document.index_status == Document.INDEX_INDEXED
            and document.index_model == settings.EMBEDDING_MODEL
            and document.index_fingerprint == sections_fingerprint(document.extracted_text))


class QdrantHybridRanker:
    name = "hybrid"

    def __init__(self, document):
        self.document = document
        self.fallback = Bm25Ranker()

    def rank(self, sections, question):
        fallback_order, fallback_name = self.fallback.rank(sections, question)
        try:
            hits = store.search(question, embeddings.embed_query(question), [self.document.id],
                                limit=len(sections), prefetch=len(sections))
        except (embeddings.EmbeddingError, store.StoreError) as exc:
            logger.warning("Hybrid retrieval unavailable for doc_id=%s, using BM25: %s", self.document.id, exc)
            return fallback_order, fallback_name
        except Exception:
            logger.exception("Hybrid retrieval failed for doc_id=%s, using BM25", self.document.id)
            return fallback_order, fallback_name
        order, seen = [], set()
        for hit in hits:
            i = hit.get("section")
            if isinstance(i, int) and 0 <= i < len(sections) and i not in seen:
                order.append(i)
                seen.add(i)
        if not order:
            return fallback_order, fallback_name
        # Sections the store did not return keep their keyword order after the hybrid hits.
        order += [i for i in fallback_order if i not in seen]
        return order, self.name


def for_document(document):
    """The best available ranker for this document."""
    return QdrantHybridRanker(document) if index_usable(document) else Bm25Ranker()
