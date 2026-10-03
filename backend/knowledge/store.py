"""
Local knowledge store: one embedded Qdrant Edge shard on this machine.

Each indexed document section is one point:
    vectors  "dense"  - local embedding (EMBEDDING_MODEL, cosine)
             "bm25"   - Qdrant Edge's own BM25 sparse vector (IDF applied by the shard)
    payload  document_id, document_name, file_type, section, page, start, text,
             fingerprint, embedding_model, indexed_at

Search is hybrid (see search()): semantic similarity ranks the sections, so "pump failure"
finds "P-101 stopped working"; identifiers in the query (tags, report numbers) boost the
sections that contain them, and BM25 hits are added as candidates. Qdrant Edge runs in-process (no server); the data lives in
KNOWLEDGE_STORE_DIR and survives restarts.

A shard can be opened by one process at a time. The server opens it on first use
and keeps it open; a management command run while the server holds it gets
StoreBusyError (use the /api/knowledge/ endpoints instead).
"""

import json
import logging
import threading
import uuid
from pathlib import Path

from django.conf import settings

from documents.retrieval import tokenize

logger = logging.getLogger(__name__)

DENSE = "dense"
SPARSE = "bm25"
SCHEMA_VERSION = 1
META_FILE = "mrpl_store.json"
_POINT_NS = uuid.UUID("3f1c2b7e-8f0a-4d7e-9a51-6c2d1e0b9a47")

_lock = threading.RLock()
_shard = None
_shard_path = None
_bm25 = None



class StoreError(Exception):
    """The knowledge store cannot be used. str(exc) is safe to show."""


class StoreBusyError(StoreError):
    pass


class StoreMismatchError(StoreError):
    pass


def _qe():
    try:
        import qdrant_edge
    except ImportError as exc:  # pragma: no cover - dependency is in requirements.txt
        raise StoreError("Qdrant Edge (qdrant-edge-py) is not installed.") from exc
    return qdrant_edge


def store_dir() -> Path:
    return Path(settings.KNOWLEDGE_STORE_DIR)


def point_id(document_id, section) -> str:
    return str(uuid.uuid5(_POINT_NS, f"doc:{document_id}:section:{section}"))


def bm25():
    """Qdrant Edge's BM25 sparse encoder (same config for indexing and queries)."""
    global _bm25
    if _bm25 is None:
        qe = _qe()
        _bm25 = qe.Bm25(qe.Bm25Config(language="english"))
    return _bm25


def _read_meta(path):
    try:
        return json.loads((path / META_FILE).read_text())
    except (OSError, ValueError):
        return None


def _open(path, dim):
    qe = _qe()
    existed = (path / "edge_config.json").exists()
    meta = _read_meta(path) if existed else None
    if existed and meta and meta.get("embedding_model") != settings.EMBEDDING_MODEL:
        raise StoreMismatchError(
            f"The knowledge store was built with '{meta.get('embedding_model')}', not "
            f"'{settings.EMBEDDING_MODEL}'. Rebuild it: python manage.py index_documents --rebuild")
    path.mkdir(parents=True, exist_ok=True)
    try:
        if existed:
            shard = qe.EdgeShard.load(str(path))
        else:
            if dim is None:
                return None
            config = qe.EdgeConfig(
                vectors={DENSE: qe.EdgeVectorParams(size=dim, distance=qe.Distance.Cosine)},
                sparse_vectors={SPARSE: qe.EdgeSparseVectorParams(modifier=qe.Modifier.Idf)},
            )
            shard = qe.EdgeShard.create(str(path), config)
            shard.update(qe.UpdateOperation.create_field_index("document_id", qe.PayloadSchemaType.Integer))
            (path / META_FILE).write_text(json.dumps({
                "schema": SCHEMA_VERSION, "embedding_model": settings.EMBEDDING_MODEL, "dim": dim,
            }))
            logger.info("Created knowledge store at %s (dim=%d, model=%s)", path, dim, settings.EMBEDDING_MODEL)
    except Exception as exc:
        if "WouldBlock" in str(exc):
            raise StoreBusyError("The knowledge store is in use by another process (the running server). "
                                 "Use the /api/knowledge/ endpoints or stop the server first.") from exc
        raise StoreError(f"The knowledge store could not be opened: {exc}") from exc
    return shard


def get_shard(dim=None):
    """
    The open shard, opened on first use. Returns None when the store does not exist yet
    and no `dim` was given (nothing has been indexed). Call with the module lock held.
    """
    global _shard, _shard_path
    path = store_dir()
    if _shard is not None and _shard_path == path:
        return _shard
    close()
    _shard = _open(path, dim)
    _shard_path = path if _shard is not None else None
    return _shard


def close():
    """Flush and release the shard (tests, rebuilds, management commands)."""
    global _shard, _shard_path
    with _lock:
        if _shard is not None:
            try:
                _shard.flush()
                _shard.close()
            except Exception:  # pragma: no cover
                logger.exception("Closing the knowledge store failed")
        _shard, _shard_path = None, None


def _doc_filter(document_ids):
    qe = _qe()
    ids = [int(i) for i in document_ids]
    match = qe.MatchValue(ids[0]) if len(ids) == 1 else qe.MatchAny(ids)
    return qe.Filter(must=[qe.FieldCondition("document_id", match=match)])


def replace_document(document_id, points):
    """
    Replace every point of a document with `points`
    ([{"section", "dense", "text", "payload": {...}}]).
    """
    qe = _qe()
    with _lock:
        shard = get_shard(dim=len(points[0]["dense"]) if points else None)
        if shard is None:
            return 0
        shard.update(qe.UpdateOperation.delete_points_by_filter(_doc_filter([document_id])))
        if points:
            encoder = bm25()
            shard.update(qe.UpdateOperation.upsert_points([
                qe.Point(point_id(document_id, p["section"]),
                         {DENSE: p["dense"], SPARSE: encoder.embed_document(p["text"])},
                         {**p["payload"], "document_id": int(document_id), "section": p["section"],
                          "text": p["text"]})
                for p in points
            ]))
        shard.flush()
    return len(points)


def delete_document(document_id):
    qe = _qe()
    with _lock:
        shard = get_shard()
        if shard is None:
            return
        shard.update(qe.UpdateOperation.delete_points_by_filter(_doc_filter([document_id])))
        shard.flush()


def identifiers(text):
    """Query tokens that name something exactly: tags, report numbers, standards (contain a digit)."""
    return {t for t in tokenize(text) if any(c.isdigit() for c in t) and len(t) >= 2}


def _scored(shard, request):
    return {h.id: h for h in shard.query(request)}


def search(query_text, query_vector, document_ids=None, limit=10, prefetch=50):
    """
    Search -> [{"score", "dense_score", "identifier_match", "document_id", "section", "page",
    "text", ...payload}], best first.

    Ranking is semantic first: cosine similarity of the local embeddings. Sections that
    contain an identifier from the query (P-2210B, INS-2026-0417, API 579 ...) get
    KNOWLEDGE_IDENTIFIER_BOOST x the share of those identifiers they contain, so the right
    report wins among many similar ones. Qdrant's BM25 hits are added as candidates so an
    exact-tag section cannot be missed by the dense prefetch; their cosine score is fetched
    from the shard. (Rank fusion of dense + BM25 was measured and rejected: one shared word,
    "machine" in "machine learning", outranked the right paraphrased answer.)
    query_vector=None ranks by BM25 alone (embedding model unavailable).
    """
    qe = _qe()
    flt = _doc_filter(document_ids) if document_ids else None
    sparse = qe.Query.Nearest(bm25().embed_query(query_text), using=SPARSE)
    with _lock:
        shard = get_shard()
        if shard is None:
            return []
        keyword = _scored(shard, qe.QueryRequest(limit=prefetch, query=sparse, filter=flt, with_payload=True))
        if query_vector is None:
            hits = sorted(keyword.values(), key=lambda h: -h.score)[:limit]
            return [{"score": h.score, "dense_score": None, "identifier_match": 0.0, **(h.payload or {})}
                    for h in hits]
        dense_q = qe.Query.Nearest(query_vector, using=DENSE)
        dense = _scored(shard, qe.QueryRequest(limit=prefetch, query=dense_q, filter=flt, with_payload=True))
        missing = set(keyword) - set(dense)
        if missing:
            only = qe.Filter(must=[qe.HasIdCondition(missing)] + ([flt] if flt else []))
            dense.update(_scored(shard, qe.QueryRequest(limit=len(missing), query=dense_q, filter=only,
                                                        with_payload=True)))
    wanted = identifiers(query_text)
    boost = float(getattr(settings, "KNOWLEDGE_IDENTIFIER_BOOST", 0.2))
    out = []
    for h in dense.values():
        payload = h.payload or {}
        match = len(wanted & set(tokenize(payload.get("text") or ""))) / len(wanted) if wanted else 0.0
        out.append({"score": h.score + boost * match, "dense_score": h.score, "identifier_match": match,
                    **payload})
    out.sort(key=lambda r: -r["score"])
    return out[:limit]


def set_document_payload(document_id, payload):
    """Set payload fields on every point of a document (e.g. a new classification)."""
    qe = _qe()
    with _lock:
        shard = get_shard()
        if shard is None:
            return
        shard.update(qe.UpdateOperation.set_payload_by_filter(_doc_filter([document_id]), payload))
        shard.flush()


def scroll_sections(document_ids=None, page_size=256):
    """Payloads of every indexed section (optionally only these documents), in no particular order."""
    qe = _qe()
    if document_ids is not None and not document_ids:
        return []
    flt = _doc_filter(document_ids) if document_ids else None
    out, offset = [], None
    with _lock:
        shard = get_shard()
        if shard is None:
            return []
        while True:
            records, offset = shard.scroll(qe.ScrollRequest(offset=offset, limit=page_size, filter=flt,
                                                            with_payload=True))
            out.extend(r.payload or {} for r in records)
            if offset is None:
                break
    return out


def count(document_ids=None):
    qe = _qe()
    with _lock:
        shard = get_shard()
        if shard is None:
            return 0
        return shard.count(qe.CountRequest(exact=True, filter=_doc_filter(document_ids) if document_ids else None))


def indexed_document_ids():
    """Document ids that have at least one point (for status and orphan cleanup)."""
    qe = _qe()
    with _lock:
        shard = get_shard()
        if shard is None:
            return set()
        response = shard.facet(qe.FacetRequest(key="document_id", limit=100000, exact=True))
    return {int(hit.value) for hit in response.hits}


def info():
    """Store status for APIs / commands (never raises)."""
    meta = _read_meta(store_dir()) or {}
    out = {"path": str(store_dir()), "exists": (store_dir() / "edge_config.json").exists(),
           "embedding_model": meta.get("embedding_model"), "dim": meta.get("dim"),
           "configured_model": settings.EMBEDDING_MODEL, "points": 0}
    try:
        out["points"] = count()
        out["state"] = "ready" if out["exists"] else "empty"
    except StoreError as exc:
        out.update(state="unavailable", reason=str(exc))
    return out
