"""
Document -> local knowledge store.

After text extraction (documents/jobs.py) a ready document is split with the same
`split_sections` used at question time, each section is embedded by the local
embedding model and stored in Qdrant Edge with its page and section number. The
document records which text was indexed (index_fingerprint), so retrieval only
uses the index while it matches the current text.

Indexing never makes a document unusable: if embedding or the store fails the
document stays ready, index_status is "failed" and questions use in-memory BM25.
"""

import logging

from django.conf import settings
from django.utils import timezone

from documents.models import Document
from documents.retrieval import split_sections, sections_fingerprint

from . import embeddings, store

logger = logging.getLogger(__name__)


def enabled():
    return bool(getattr(settings, "KNOWLEDGE_INDEXING", True))


def _embedding_text(doc, section):
    """Text that is embedded: the section plus where it comes from (helps cross-document search)."""
    where = f"Document: {doc.original_name}" + (f", page {section['page']}" if section["page"] else "")
    heading = f"Section: {section['heading']}\n" if section.get("heading") else ""
    return f"{where}\n{heading}{section['text']}"


def index_document(doc_id, force=False):
    """
    (Re)index one document. Returns the document's index_status afterwards.
    Skips documents whose index already matches their text unless force=True.
    """
    doc = Document.objects.filter(pk=doc_id).first()
    if doc is None:
        return None
    if doc.status != Document.STATUS_READY or not (doc.extracted_text or "").strip():
        Document.objects.filter(pk=doc_id).update(index_status=Document.INDEX_NONE, index_chunks=0)
        return Document.INDEX_NONE
    fingerprint = sections_fingerprint(doc.extracted_text)
    if (not force and doc.index_status == Document.INDEX_INDEXED and doc.index_fingerprint == fingerprint
            and doc.index_model == settings.EMBEDDING_MODEL):
        return Document.INDEX_INDEXED

    Document.objects.filter(pk=doc_id).update(index_status=Document.INDEX_PENDING, index_error="")
    sections = split_sections(doc.extracted_text, doc.page_offsets or None)
    try:
        vectors = embeddings.embed([_embedding_text(doc, s) for s in sections])
        now = timezone.now()
        stored = store.replace_document(doc.id, [
            {"section": i, "dense": vec, "text": s["text"], "payload": {
                "document_name": doc.original_name, "file_type": doc.file_type, "page": s["page"],
                "start": s["start"], "heading": s.get("heading"), "fingerprint": fingerprint,
                "classification": doc.classification,
                "embedding_model": settings.EMBEDDING_MODEL, "indexed_at": now.isoformat(),
            }}
            for i, (s, vec) in enumerate(zip(sections, vectors))
        ])
    except (embeddings.EmbeddingError, store.StoreError) as exc:
        return _failed(doc_id, str(exc))
    except Exception as exc:
        logger.exception("Indexing crashed: doc_id=%s", doc_id)
        return _failed(doc_id, f"Indexing failed ({exc.__class__.__name__}).")
    Document.objects.filter(pk=doc_id).update(
        index_status=Document.INDEX_INDEXED, index_chunks=stored, index_model=settings.EMBEDDING_MODEL,
        index_fingerprint=fingerprint, index_error="", indexed_at=now,
    )
    logger.info("Indexed doc_id=%s: %d section(s) into the local knowledge store", doc_id, stored)
    return Document.INDEX_INDEXED


def _failed(doc_id, message):
    logger.warning("Indexing failed: doc_id=%s (%s)", doc_id, message)
    Document.objects.filter(pk=doc_id).update(index_status=Document.INDEX_FAILED, index_error=message[:300])
    return Document.INDEX_FAILED


def index_after_extraction(doc_id):
    """Hook for documents/jobs.py: index a freshly extracted document when indexing is on."""
    if enabled():
        index_document(doc_id, force=True)


def pending_documents():
    """Ready documents whose index is missing, failed or out of date."""
    out = []
    for doc in Document.objects.filter(status=Document.STATUS_READY).exclude(extracted_text=""):
        if (doc.index_status != Document.INDEX_INDEXED or doc.index_model != settings.EMBEDDING_MODEL
                or doc.index_fingerprint != sections_fingerprint(doc.extracted_text)):
            out.append(doc.id)
    return out


def prune_orphans():
    """Remove points of documents that no longer exist. Returns the number of documents removed."""
    orphans = store.indexed_document_ids() - set(Document.objects.values_list("id", flat=True))
    for doc_id in orphans:
        store.delete_document(doc_id)
    return len(orphans)
