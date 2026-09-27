"""
Local OCR processor (PaddleOCR).

Kept separate from model execution: this module turns images / scanned PDF
pages into text and knows nothing about Ollama or the model router.

Runs on CPU so it does not compete with Ollama for the 8 GB of GPU memory.
PaddleOCR downloads its model weights once on first use (to ~/.paddlex);
after that it runs fully offline. Document contents never leave this machine.
"""

import logging
import os
import threading
import time

import numpy as np
import pymupdf
from django.conf import settings

logger = logging.getLogger(__name__)

# Skip PaddleX's network connectivity check to model hosts on every start-up.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

_engine = None
_engine_lock = threading.Lock()  # PaddleOCR predictors are not thread-safe


class OCRError(Exception):
    """Raised when local OCR cannot be performed."""


def _get_engine():
    global _engine
    if _engine is None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise OCRError("PaddleOCR is not installed on the server.") from exc
        kwargs = dict(
            device="cpu",
            # oneDNN crashes with PaddlePaddle 3.3's new executor on CPU.
            enable_mkldnn=False,
            cpu_threads=getattr(settings, "OCR_CPU_THREADS", 8),
            # Plain scanned pages: skip the optional orientation/unwarping models.
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        det_model = getattr(settings, "OCR_DET_MODEL", "")
        rec_model = getattr(settings, "OCR_REC_MODEL", "")
        if det_model or rec_model:
            if det_model:
                kwargs["text_detection_model_name"] = det_model
            if rec_model:
                kwargs["text_recognition_model_name"] = rec_model
        else:
            kwargs["lang"] = getattr(settings, "OCR_LANG", "en")
        started = time.monotonic()
        _engine = PaddleOCR(**kwargs)
        logger.info("PaddleOCR engine loaded on CPU in %.1fs", time.monotonic() - started)
    return _engine


def _pixmap_to_array(pix: "pymupdf.Pixmap") -> np.ndarray:
    """Convert a PyMuPDF pixmap to a BGR uint8 array as expected by PaddleOCR."""
    if pix.alpha or pix.n not in (1, 3):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix, 0)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 1:
        arr = np.repeat(arr, 3, axis=2)
    return np.ascontiguousarray(arr[:, :, ::-1])  # RGB -> BGR


def _recognize(image: np.ndarray) -> dict:
    with _engine_lock:
        result = _get_engine().predict(image)[0]
    texts = [t for t in result["rec_texts"] if t and t.strip()]
    scores = list(result["rec_scores"])[: len(texts)]
    return {
        "text": "\n".join(texts),
        "lines": len(texts),
        "confidence": round(float(np.mean(scores)), 3) if scores else 0.0,
    }


def ocr_image(image_bytes: bytes) -> dict:
    """OCR a PNG/JPEG image. Returns {"text", "lines", "confidence"}."""
    try:
        pix = pymupdf.Pixmap(image_bytes)
    except Exception as exc:
        raise OCRError("The image could not be decoded.") from exc
    started = time.monotonic()
    result = _recognize(_pixmap_to_array(pix))
    logger.info(
        "OCR image: %dx%d lines=%d confidence=%.3f duration=%.1fs",
        pix.width, pix.height, result["lines"], result["confidence"], time.monotonic() - started,
    )
    return result


def ocr_pdf_page(page: "pymupdf.Page") -> dict:
    """Render one PDF page locally and OCR it. Returns {"text", "lines", "confidence"}."""
    dpi = getattr(settings, "OCR_PDF_DPI", 200)
    started = time.monotonic()
    pix = page.get_pixmap(dpi=dpi)
    result = _recognize(_pixmap_to_array(pix))
    logger.info(
        "OCR PDF page %d: lines=%d confidence=%.3f duration=%.1fs",
        page.number + 1, result["lines"], result["confidence"], time.monotonic() - started,
    )
    return result
