"""Search across indexed documents (knowledge-base Q&A, the search API and the search_knowledge command)."""

from django.conf import settings

from documents.models import Document
from documents.retrieval import sections_fingerprint

from . import embeddings, store

SNIPPET_CHARS = 400


def search_sections(query, document_ids=None, limit=8):
    """
    Hybrid search -> (hits, method); hits carry the full section text and "document" (the
    Document). Hits from deleted documents or from an index that no longer matches the
    document's text are dropped. method: "hybrid", or "bm25" when the embedding model is
    unavailable (keyword search in Qdrant Edge only).
    """
    try:
        vector, method = embeddings.embed_query(query), "hybrid"
    except embeddings.EmbeddingError:
        vector, method = None, "bm25"
    raw = store.search(query, vector, document_ids=document_ids, limit=limit * 3, prefetch=max(50, limit * 6))
    docs = Document.objects.in_bulk({h.get("document_id") for h in raw if isinstance(h.get("document_id"), int)})
    current = {i: sections_fingerprint(d.extracted_text) for i, d in docs.items()}
    hits = []
    for h in raw:
        doc = docs.get(h.get("document_id"))
        if doc is None or h.get("fingerprint") != current[doc.id] or h.get("embedding_model") != settings.EMBEDDING_MODEL:
            continue
        hits.append({**h, "document": doc})
        if len(hits) == limit:
            break
    return hits, method


def search(query, document_ids=None, limit=8):
    """API form of search_sections: plain fields and a text snippet."""
    hits, method = search_sections(query, document_ids, limit)
    out = []
    for h in hits:
        doc, text = h["document"], h.get("text") or ""
        out.append({
            "document_id": doc.id, "document_name": doc.original_name, "classification": doc.classification,
            "page": h.get("page"), "section": h.get("section"), "heading": h.get("heading"),
            "score": round(h["score"], 4),
            "text": text[:SNIPPET_CHARS] + ("…" if len(text) > SNIPPET_CHARS else ""),
        })
    return out, method
