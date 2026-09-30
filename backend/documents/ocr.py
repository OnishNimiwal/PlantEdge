"""
Local OCR processor (PaddleOCR).

Kept separate from model execution: this module turns images / scanned PDF
pages into text and knows nothing about Ollama or the model router.

Runs on CPU so it does not compete with Ollama for the 8 GB of GPU memory.
PaddleOCR downloads its model weights once on first use (to ~/.paddlex);
after that it runs fully offline. Document contents never leave this machine.

Configuration (settings / .env):
  OCR_MODEL_PROFILE   server (default, most accurate) | mobile (~4x faster on CPU)
  OCR_DET_MODEL / OCR_REC_MODEL   explicit PaddleOCR model names (override the profile)
  OCR_LANG            default language; OCR_ALLOWED_LANGS lists what users may pick
  OCR_USE_DOC_ORIENTATION / OCR_USE_TEXTLINE_ORIENTATION / OCR_USE_UNWARPING
                      optional preprocessing models (see samples/ocr_benchmark.py results)
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

_engines = {}                   # one engine per (language, configuration)
_engine_lock = threading.Lock()  # PaddleOCR predictors are not thread-safe

# PaddleOCR language codes offered to users, with display names.
LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi (Devanagari)", "mr": "Marathi (Devanagari)",
    "ka": "Kannada", "ta": "Tamil", "te": "Telugu", "ml": "Malayalam",
    "ch": "Chinese & English", "latin": "Latin-script languages",
}

# Lighter CPU models ("mobile" profile). Only languages listed here have a mobile variant.
MOBILE_MODELS = {
    "en": ("PP-OCRv5_mobile_det", "en_PP-OCRv5_mobile_rec"),
}


class OCRError(Exception):
    """Raised when local OCR cannot be performed."""


def allowed_languages() -> list:
    langs = getattr(settings, "OCR_ALLOWED_LANGS", None) or [getattr(settings, "OCR_LANG", "en")]
    return [lang for lang in langs if lang in LANGUAGE_NAMES]


def default_language() -> str:
    lang = getattr(settings, "OCR_LANG", "en")
    return lang if lang in allowed_languages() else (allowed_languages() or ["en"])[0]


def engine_config(lang: str) -> dict:
    """PaddleOCR constructor arguments for a language under the current settings."""
    kwargs = dict(
        device="cpu",
        # oneDNN crashes with PaddlePaddle 3.3's new executor on CPU.
        enable_mkldnn=False,
        cpu_threads=getattr(settings, "OCR_CPU_THREADS", 8),
        use_doc_orientation_classify=getattr(settings, "OCR_USE_DOC_ORIENTATION", False),
        use_doc_unwarping=getattr(settings, "OCR_USE_UNWARPING", False),
        use_textline_orientation=getattr(settings, "OCR_USE_TEXTLINE_ORIENTATION", False),
    )
    det_model = getattr(settings, "OCR_DET_MODEL", "")
    rec_model = getattr(settings, "OCR_REC_MODEL", "")
    profile = getattr(settings, "OCR_MODEL_PROFILE", "server")
    if det_model or rec_model:
        if det_model:
            kwargs["text_detection_model_name"] = det_model
        if rec_model:
            kwargs["text_recognition_model_name"] = rec_model
    elif profile == "mobile" and lang in MOBILE_MODELS:
        kwargs["text_detection_model_name"], kwargs["text_recognition_model_name"] = MOBILE_MODELS[lang]
    else:
        if profile == "mobile":
            logger.warning("No mobile OCR model for lang=%s; using the server profile", lang)
        kwargs["lang"] = lang
    return kwargs


def _get_engine(lang: str):
    kwargs = engine_config(lang)
    key = tuple(sorted((k, str(v)) for k, v in kwargs.items()))
    if key not in _engines:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise OCRError("PaddleOCR is not installed on the server.") from exc
        started = time.monotonic()
        try:
            _engines[key] = PaddleOCR(**kwargs)
        except Exception as exc:
            logger.exception("PaddleOCR engine failed to load for lang=%s", lang)
            raise OCRError(
                f"The OCR engine for language '{lang}' could not be loaded. Its model files may "
                "not be downloaded on this server yet."
            ) from exc
        logger.info("PaddleOCR engine loaded on CPU in %.1fs (lang=%s, %s)",
                    time.monotonic() - started, lang,
                    kwargs.get("text_recognition_model_name", "default models"))
    return _engines[key]


def _pixmap_to_array(pix: "pymupdf.Pixmap") -> np.ndarray:
    """Convert a PyMuPDF pixmap to a BGR uint8 array as expected by PaddleOCR."""
    if pix.alpha or pix.n not in (1, 3):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix, 0)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 1:
        arr = np.repeat(arr, 3, axis=2)
    return np.ascontiguousarray(arr[:, :, ::-1])  # RGB -> BGR


def detect_complex_layout(boxes) -> bool:
    """
    Heuristic: flag tables / multi-column pages, where the flattened line order
    may interleave columns. True when at least 3 visual rows (and 30% of rows)
    contain several text boxes separated by wide horizontal gaps.
    """
    if boxes is None or len(boxes) < 4:
        return False
    boxes = np.asarray(boxes, dtype=float).reshape(len(boxes), -1)[:, :4]  # x1, y1, x2, y2
    heights = boxes[:, 3] - boxes[:, 1]
    tol = max(float(np.median(heights)) * 0.5, 1.0)
    order = np.argsort((boxes[:, 1] + boxes[:, 3]) / 2)
    rows, current, last_y = [], [], None
    for i in order:
        y = (boxes[i, 1] + boxes[i, 3]) / 2
        if last_y is not None and abs(y - last_y) > tol:
            rows.append(current)
            current = []
        current.append(i)
        last_y = y
    rows.append(current)
    gap_min = float(np.median(heights)) * 3
    split_rows = 0
    for row in rows:
        xs = sorted((boxes[i, 0], boxes[i, 2]) for i in row)
        if any(nxt[0] - prev[1] > gap_min for prev, nxt in zip(xs, xs[1:])):
            split_rows += 1
    return split_rows >= 3 and split_rows / len(rows) >= 0.3


_last_used = 0.0
_unload_timer = None


def _schedule_unload():
    """Drop idle OCR engines after OCR_IDLE_UNLOAD_SECONDS to give the RAM back."""
    global _unload_timer
    delay = int(getattr(settings, "OCR_IDLE_UNLOAD_SECONDS", 600))
    if delay <= 0:
        return
    if _unload_timer is not None:
        _unload_timer.cancel()
    _unload_timer = threading.Timer(delay, _unload_if_idle, args=(delay,))
    _unload_timer.daemon = True
    _unload_timer.start()


def _unload_if_idle(delay):
    import gc
    with _engine_lock:
        if _engines and time.monotonic() - _last_used >= delay - 1:
            count = len(_engines)
            _engines.clear()
            gc.collect()
            logger.info("OCR engine(s) unloaded after %ds idle (%d engine(s))", delay, count)


def engines_loaded() -> int:
    return len(_engines)


def _recognize(image: np.ndarray, lang: str) -> dict:
    global _last_used
    with _engine_lock:
        result = _get_engine(lang).predict(image)[0]
        _last_used = time.monotonic()
    _schedule_unload()
    texts = [t for t in result["rec_texts"] if t and t.strip()]
    scores = list(result["rec_scores"])[: len(texts)]
    boxes = result.get("rec_boxes")
    return {
        "text": "\n".join(texts),
        "lines": len(texts),
        "confidence": round(float(np.mean(scores)), 3) if scores else 0.0,
        "complex_layout": detect_complex_layout(boxes),
    }


def ocr_image(image_bytes: bytes, lang: str = None) -> dict:
    """OCR a PNG/JPEG image. Returns {"text", "lines", "confidence", "complex_layout"}."""
    lang = lang or default_language()
    try:
        pix = pymupdf.Pixmap(image_bytes)
    except Exception as exc:
        raise OCRError("The image could not be decoded.") from exc
    started = time.monotonic()
    result = _recognize(_pixmap_to_array(pix), lang)
    logger.info(
        "OCR image: %dx%d lang=%s lines=%d confidence=%.3f complex_layout=%s duration=%.1fs",
        pix.width, pix.height, lang, result["lines"], result["confidence"],
        result["complex_layout"], time.monotonic() - started,
    )
    return result


def ocr_pdf_page(page: "pymupdf.Page", lang: str = None) -> dict:
    """Render one PDF page locally and OCR it. Returns {"text", "lines", "confidence", "complex_layout"}."""
    lang = lang or default_language()
    dpi = getattr(settings, "OCR_PDF_DPI", 200)
    started = time.monotonic()
    pix = page.get_pixmap(dpi=dpi)
    result = _recognize(_pixmap_to_array(pix), lang)
    logger.info(
        "OCR PDF page %d: lang=%s lines=%d confidence=%.3f complex_layout=%s duration=%.1fs",
        page.number + 1, lang, result["lines"], result["confidence"],
        result["complex_layout"], time.monotonic() - started,
    )
    return result
