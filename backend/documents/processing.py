"""
Document processor: turns documents / images into model-ready inputs.

Shared by the chat view and the Document Assistant. It calls the OCR processor
(ocr.py) and renders page images, but never selects or calls a model - the
router decides WHICH model, the execution layer HOW to call it.
"""

import base64
import re

import pymupdf
from django.conf import settings

from . import ocr

OCRError = ocr.OCRError

_PAGE_RANGE = re.compile(r"\bpages?\s+(\d+)(?:\s*(?:-|–|to|and|&|,)\s*(\d+))?", re.IGNORECASE)


def ocr_images(images_b64, lang=None) -> dict:
    """
    OCR each attached (already size-checked) image locally.
    Returns {"text": block for the model prompt, "results": [{lines, confidence, complex_layout}]}.
    """
    blocks, results = [], []
    for idx, b64 in enumerate(images_b64, start=1):
        r = ocr.ocr_image(base64.b64decode(b64), lang)
        results.append({k: r[k] for k in ("lines", "confidence", "complex_layout")})
        note = " (table/multi-column layout: reading order may be wrong)" if r["complex_layout"] else ""
        blocks.append(
            f"=== OCR TEXT OF ATTACHED IMAGE {idx} (local PaddleOCR, recognition confidence "
            f"{r['confidence']:.2f}{note}) ===\n{r['text'] or '[no text detected]'}\n=== END OCR TEXT ==="
        )
    return {"text": "\n\n".join(blocks), "results": results}


def requested_pages(question: str, page_count: int) -> list:
    """
    Pages the user asked about ("page 3", "pages 2-3"), clamped to the document and
    to VISION_MAX_PDF_PAGES. Defaults to page 1.
    """
    limit = max(1, int(getattr(settings, "VISION_MAX_PDF_PAGES", 2)))
    match = _PAGE_RANGE.search(question or "")
    if not match or page_count < 1:
        return [1]
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else start
    start, end = sorted((start, end))
    pages = [p for p in range(start, end + 1) if 1 <= p <= page_count]
    return pages[:limit] or [1]


def document_images_b64(document, pages=(1,)) -> list:
    """
    Render the document (image file, or the given PDF pages) as PNGs no larger
    than VISION_MAX_SIDE, base64-encoded. Returns [] for documents without visuals.
    """
    if document.file_type not in ("PDF", "PNG", "JPG") or not document.file:
        return []
    document.file.open("rb")
    try:
        data = document.file.read()
    finally:
        document.file.close()
    filetype = {"PDF": "pdf", "PNG": "png", "JPG": "jpeg"}[document.file_type]
    out = []
    with pymupdf.open(stream=data, filetype=filetype) as doc:
        for number in pages:
            if not 1 <= number <= len(doc):
                continue
            page = doc[number - 1]
            # Large images exhaust the 8 GB GPU in the vision model, so render at most this size.
            zoom = min(settings.VISION_MAX_SIDE / max(page.rect.width, page.rect.height), 3.0)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            out.append(base64.b64encode(pix.tobytes("png")).decode())
    return out
