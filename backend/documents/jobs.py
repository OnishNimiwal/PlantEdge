"""
Background document processing (text extraction / OCR).

Uploads return immediately; a single worker thread extracts text so a 20-page scan
does not hold the HTTP request open for minutes. One worker is enough because OCR
is serialised anyway (PaddleOCR predictors are not thread-safe).

This is an in-process queue: it suits the single-server deployment used here.
Jobs that were queued when the server stopped are detected and marked failed
(see `mark_interrupted`); a multi-process deployment would need a real task queue.
"""

import logging
import queue
import threading

from django.db import close_old_connections

logger = logging.getLogger(__name__)

_queue = queue.Queue()
_active = set()
_lock = threading.Lock()
_worker = None


def active_ids():
    with _lock:
        return set(_active)


def submit(doc_id, lang):
    """Queue a document for extraction (starts the worker on first use)."""
    global _worker
    with _lock:
        _active.add(doc_id)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, name="document-worker", daemon=True)
            _worker.start()
    _queue.put((doc_id, lang))


def _worker_loop():
    while True:
        doc_id, lang = _queue.get()
        try:
            process(doc_id, lang)
        except Exception:
            logger.exception("Document job crashed: doc_id=%s", doc_id)
        finally:
            with _lock:
                _active.discard(doc_id)
            close_old_connections()


def process(doc_id, lang):
    """Extract text for one document and store the result (used by the worker and in sync mode)."""
    from .extractors import extract_document, DocumentExtractionError
    from .models import Document

    doc = Document.objects.filter(pk=doc_id).first()
    if doc is None:
        return  # deleted while queued

    def progress(done, total):
        Document.objects.filter(pk=doc_id).update(progress_done=done, progress_total=total)

    Document.objects.filter(pk=doc_id).update(status=Document.STATUS_PROCESSING)
    try:
        doc.file.open("rb")
        try:
            extraction = extract_document(doc.file, doc.file_type, lang=lang, progress=progress)
        finally:
            doc.file.close()
    except DocumentExtractionError as exc:
        from monitoring.usage import record_failure
        record_failure("extraction", "document", exc)
        Document.objects.filter(pk=doc_id).update(status=Document.STATUS_FAILED, processing_error=str(exc))
        logger.info("Document job failed: doc_id=%s (%s)", doc_id, exc)
        return
    except Exception as exc:
        logger.exception("Document job error: doc_id=%s", doc_id)
        from monitoring.usage import record_failure
        record_failure("extraction", "document", exc)
        Document.objects.filter(pk=doc_id).update(
            status=Document.STATUS_FAILED, processing_error="The document could not be processed.",
        )
        return
    Document.objects.filter(pk=doc_id).update(
        status=Document.STATUS_READY,
        extracted_text=extraction["text"],
        extraction_method=extraction["method"],
        ocr_pages=extraction["ocr_pages"],
        ocr_confidence=extraction["ocr_confidence"],
        page_count=extraction["page_count"],
        page_offsets=extraction.get("page_offsets") or [],
        ocr_pages_skipped=extraction["ocr_pages_skipped"],
        truncated=extraction["truncated"],
        original_chars=extraction["original_chars"],
        ocr_lang=lang if extraction["ocr_pages"] else "",
        complex_layout=extraction["complex_layout"],
        vision_fallback_pages=extraction.get("vision_fallback_pages", 0),
        processing_error="",
    )
    logger.info("Document job done: doc_id=%s method=%s pages=%s", doc_id, extraction["method"],
                extraction["page_count"])


def mark_interrupted(doc):
    """A 'processing' document with no queued job was interrupted (e.g. server restart)."""
    from .models import Document
    if doc.status in (Document.STATUS_QUEUED, Document.STATUS_PROCESSING) and doc.id not in active_ids():
        Document.objects.filter(pk=doc.id).update(
            status=Document.STATUS_FAILED,
            processing_error="Processing was interrupted (the server restarted). Please upload the file again.",
        )
        doc.refresh_from_db()
    return doc
