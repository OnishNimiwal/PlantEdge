"""
Data classification policy: the single place that decides what may leave this site.

Levels (most open -> most restricted):
    public, shareable   may leave the site (e.g. be synchronised to the central cloud)
    internal            stays on this site (the default for anything not classified)
    confidential        stays on this site; marked in answers that use it

Rules
  * Every document has a level. Unclassified uploads get DEFAULT_CLASSIFICATION
    (internal), so nothing is shareable unless someone decided so.
  * The content scan (sensitivity.py) can only RAISE a level. Lowering a level needs
    a reason; lowering below what the scan found is refused unless
    CLASSIFICATION_ALLOW_OVERRIDE is on.
  * Egress (guard_egress) is decided per section, at the moment of egress, from the
    database (source of truth, not the index payload), a fresh content scan of the
    section, and the index being current. A section is released only when all three
    allow it: a shareable document's section that contains an email address or a
    password is still blocked, whatever its label.
  * Every decision is written to PolicyEvent.

Any code that sends knowledge off this machine must take its items from guard_egress().
"""

import hashlib
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from documents.models import Document
from documents.retrieval import sections_fingerprint

from . import sensitivity, store
from .models import PolicyEvent

logger = logging.getLogger(__name__)

LEVELS = [Document.CLASS_PUBLIC, Document.CLASS_SHAREABLE, Document.CLASS_INTERNAL, Document.CLASS_CONFIDENTIAL]
EGRESS_LEVELS = {Document.CLASS_PUBLIC, Document.CLASS_SHAREABLE}
DESCRIPTIONS = {
    Document.CLASS_PUBLIC: "Public information; may leave the site.",
    Document.CLASS_SHAREABLE: "Company knowledge that may be shared with the central knowledge base.",
    Document.CLASS_INTERNAL: "Site information; stays on this site.",
    Document.CLASS_CONFIDENTIAL: "Confidential; never leaves this site.",
}
# Fields an egress item may carry. Nothing else (file paths, internal metadata) leaves.
EGRESS_FIELDS = ("document_id", "document_name", "classification", "section", "page", "heading", "text",
                 "content_sha256")


class PolicyError(Exception):
    """An invalid classification request. str(exc) is safe to show."""


class PolicyRefused(PolicyError):
    """A valid request the policy does not allow (e.g. lowering below the scanned level)."""


def rank(level):
    return LEVELS.index(level)


def stricter(a, b):
    return a if rank(a) >= rank(b) else b


def default_level():
    level = getattr(settings, "DEFAULT_CLASSIFICATION", Document.CLASS_INTERNAL)
    return level if level in LEVELS else Document.CLASS_INTERNAL


def may_leave_site(level):
    return level in EGRESS_LEVELS


def required_level(markers):
    """The lowest level the scan findings allow, or None when nothing was found."""
    levels = [m["min_level"] for m in markers]
    return max(levels, key=rank) if levels else None


def record(event, document=None, reason="", client="", from_level="", to_level="", **detail):
    return PolicyEvent.objects.create(
        event=event, document=document, document_name=document.original_name if document else "",
        from_level=from_level, to_level=to_level, reason=reason[:500], client=client[:64], detail=detail,
    )


def _sync_index_payload(document):
    """Keep the level on the document's indexed sections (used by search filters / sync)."""
    if not (store.store_dir() / "edge_config.json").exists():
        return
    try:
        store.set_document_payload(document.id, {"classification": document.classification})
    except store.StoreError as exc:
        # The guard reads the database, so a stale payload can never release anything.
        logger.warning("Could not update the classification in the index: doc_id=%s (%s)", document.id, exc)


def classify_upload(document, requested=None, client=""):
    """Level chosen at upload (or the default). Called before text extraction."""
    level = requested if requested in LEVELS else default_level()
    source = Document.SOURCE_USER if requested in LEVELS else Document.SOURCE_DEFAULT
    Document.objects.filter(pk=document.pk).update(classification=level, classification_source=source,
                                                   classified_at=timezone.now())
    document.classification, document.classification_source = level, source
    record(PolicyEvent.CLASSIFIED, document, client=client, to_level=level,
           reason="Chosen at upload" if source == Document.SOURCE_USER else "Default level (not classified at upload)")


def apply_content_scan(document):
    """After extraction: store the scan findings and raise the level when they require it."""
    markers = sensitivity.scan(document.extracted_text)
    needed = required_level(markers)
    updates = {"sensitivity_markers": markers}
    old = document.classification
    if needed and rank(needed) > rank(old):
        updates.update(classification=needed, classification_source=Document.SOURCE_DETECTED,
                       classified_at=timezone.now())
    Document.objects.filter(pk=document.pk).update(**updates)
    for key, value in updates.items():
        setattr(document, key, value)
    if document.classification != old:
        record(PolicyEvent.AUTO_ESCALATED, document, from_level=old, to_level=document.classification,
               reason=f"Content scan found: {sensitivity.summary(markers)}",
               markers=[{k: m[k] for k in ("type", "label", "count")} for m in markers])
        logger.info("Classification raised by content scan: doc_id=%s %s -> %s", document.pk, old,
                    document.classification)
    return markers


def change_classification(document, level, reason="", override=False, client=""):
    """A user changes the level. Raises PolicyError when the policy refuses."""
    if level not in LEVELS:
        raise PolicyError(f"Unknown classification '{level}'. Use one of: {', '.join(LEVELS)}.")
    old = document.classification
    if level == old:
        return document
    reason = (reason or "").strip()
    if rank(level) < rank(old):
        if not reason:
            raise PolicyError("Give a reason for lowering the classification.")
        needed = required_level(document.sensitivity_markers or [])
        if needed and rank(level) < rank(needed):
            allowed = override and getattr(settings, "CLASSIFICATION_ALLOW_OVERRIDE", False)
            if not allowed:
                found = sensitivity.summary(document.sensitivity_markers)
                record(PolicyEvent.CHANGE_REFUSED, document, client=client, from_level=old, to_level=level,
                       reason=reason, required=needed)
                raise PolicyRefused(f"The document contains {found}, so it must stay at least {needed}. "
                                  "Remove that content and upload the document again, or ask an administrator.")
    with transaction.atomic():
        Document.objects.filter(pk=document.pk).update(classification=level, classification_source=Document.SOURCE_USER,
                                                       classified_at=timezone.now())
        document.classification, document.classification_source = level, Document.SOURCE_USER
        record(PolicyEvent.CHANGED, document, client=client, from_level=old, to_level=level,
               reason=reason or "Raised", override=bool(override))
    _sync_index_payload(document)
    return document


def section_decision(document, section_text, index_current):
    """(allowed, [reasons]) for one section of `document` at egress time."""
    reasons = []
    if not may_leave_site(document.classification):
        reasons.append(f"Document is {document.classification}")
    if document.status != Document.STATUS_READY:
        reasons.append("Document is not ready")
    if not index_current:
        reasons.append("Index does not match the current document text")
    markers = sensitivity.scan(section_text)
    if markers:
        reasons.append(f"Section contains {sensitivity.summary(markers)}")
    return not reasons, reasons


def _item(document, payload):
    text = payload.get("text") or ""
    return {
        "document_id": document.id, "document_name": document.original_name,
        "classification": document.classification, "section": payload.get("section"),
        "page": payload.get("page"), "heading": payload.get("heading"), "text": text,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def guard_egress(candidates, purpose, client="", audit=True):
    """
    The egress choke point. `candidates` are index payloads (or dicts with at least
    document_id and text). Every candidate is re-checked against the database and a fresh
    content scan. Returns (allowed_items, blocked) where allowed items carry only
    EGRESS_FIELDS; blocked = [{"document_id", "document_name", "section", "reasons"}].
    With audit=True one PolicyEvent per document and outcome is written.
    """
    ids = {c.get("document_id") for c in candidates}
    docs = Document.objects.in_bulk([i for i in ids if isinstance(i, int)])
    fingerprints = {i: sections_fingerprint(d.extracted_text) for i, d in docs.items()}
    allowed, blocked = [], []
    for c in candidates:
        doc = docs.get(c.get("document_id"))
        if doc is None:
            blocked.append({"document_id": c.get("document_id"), "document_name": "", "section": c.get("section"),
                            "reasons": ["Document no longer exists"]})
            continue
        current = c.get("fingerprint") == fingerprints[doc.id]  # no fingerprint -> not verifiable -> blocked
        ok, reasons = section_decision(doc, c.get("text") or "", current)
        if ok:
            item = _item(doc, c)
            allowed.append({k: item[k] for k in EGRESS_FIELDS})
        else:
            blocked.append({"document_id": doc.id, "document_name": doc.original_name, "section": c.get("section"),
                            "reasons": reasons})
    if audit:
        _audit_egress(docs, allowed, blocked, purpose, client)
    return allowed, blocked


def _audit_egress(docs, allowed, blocked, purpose, client):
    per_doc = {}
    for a in allowed:
        per_doc.setdefault(a["document_id"], [[], []])[0].append(a["section"])
    for b in blocked:
        per_doc.setdefault(b["document_id"], [[], []])[1].append(b)
    for doc_id, (ok_sections, stopped) in per_doc.items():
        doc = docs.get(doc_id)
        if ok_sections:
            record(PolicyEvent.EGRESS_ALLOWED, doc, client=client, to_level=doc.classification if doc else "",
                   reason=purpose, sections=len(ok_sections))
        if stopped:
            reasons = sorted({r for b in stopped for r in b["reasons"]})
            record(PolicyEvent.EGRESS_BLOCKED, doc, client=client,
                   to_level=doc.classification if doc else "", reason=f"{purpose}: {'; '.join(reasons)}"[:500],
                   sections=len(stopped))
            logger.info("Egress blocked: doc_id=%s sections=%d (%s)", doc_id, len(stopped), "; ".join(reasons))


def egress_review(document_ids=None):
    """
    What would leave the site now, without sending or auditing anything:
    per ready document its level and how many indexed sections the guard would release.
    """
    docs = Document.objects.filter(status=Document.STATUS_READY)
    if document_ids:
        docs = docs.filter(id__in=document_ids)
    candidates = store.scroll_sections(document_ids=[d.id for d in docs]) if docs else []
    allowed, blocked = guard_egress(candidates, purpose="review", audit=False)
    rows = []
    for doc in docs.order_by("id"):
        ok = [a for a in allowed if a["document_id"] == doc.id]
        stopped = [b for b in blocked if b["document_id"] == doc.id]
        reasons = sorted({r for b in stopped for r in b["reasons"]})
        if not ok and not stopped:
            reasons = ["Not indexed yet"]
        rows.append({
            "document_id": doc.id, "document_name": doc.original_name, "classification": doc.classification,
            "classification_source": doc.classification_source, "may_leave_site": may_leave_site(doc.classification),
            "sections_allowed": len(ok), "sections_blocked": len(stopped), "reasons": reasons,
        })
    return {
        "documents": rows,
        "totals": {"sections_allowed": len(allowed), "sections_blocked": len(blocked),
                   "documents_shareable": sum(1 for r in rows if r["sections_allowed"])},
    }
