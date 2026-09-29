"""
Lightweight system / model health checks.

Nothing here runs inference or loads a model into GPU memory:
  - Ollama:  GET /api/version (service up), /api/tags (installed models),
             /api/ps (models currently loaded + their VRAM) - metadata only.
  - OCR:     checks the PaddleOCR package can be found and its model files are on
             disk, without importing PaddlePaddle or loading the OCR engine (~500 MB RAM).
Every check has a short timeout and returns a user-safe reason, never a stack trace.
"""

import importlib.util
import logging
import os
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

HEALTH_TIMEOUT = 3  # seconds per Ollama metadata call

CAPABILITY_LABELS = {
    "reasoning": "General Reasoning",
    "coding": "Code Generation",
    "vision": "Vision / Multimodal",
}


def _ollama_get(path):
    from chat.model_manager import ensure_local_endpoint, _session
    ensure_local_endpoint(settings.OLLAMA_URL)
    response = _session().get(f"{settings.OLLAMA_URL}{path}", timeout=HEALTH_TIMEOUT, allow_redirects=False)
    response.raise_for_status()
    return response.json()


def ollama_status():
    from chat.model_manager import NonLocalEndpointError
    try:
        version = _ollama_get("/api/version").get("version")
        tags = _ollama_get("/api/tags").get("models", [])
        loaded = _ollama_get("/api/ps").get("models", [])
    except NonLocalEndpointError:
        return {"state": "unavailable", "label": "Misconfigured",
                "reason": "The configured Ollama address is not an allowed local address."}
    except Exception as exc:
        logger.warning("Ollama health check failed: %s", exc.__class__.__name__)
        return {"state": "unavailable", "label": "Unavailable",
                "reason": "The local Ollama service is not reachable."}
    return {
        "state": "ready", "label": "Connected", "version": version,
        "installed": {m["name"]: m.get("size") for m in tags},
        "loaded": {m["name"]: {"size_vram": m.get("size_vram"), "context_length": m.get("context_length")}
                   for m in loaded},
    }


def _paddlex_models_dir():
    cache = os.environ.get("PADDLE_PDX_CACHE_HOME") or os.path.join(Path.home(), ".paddlex")
    return Path(cache) / "official_models"


def ocr_status():
    from documents import ocr
    if importlib.util.find_spec("paddleocr") is None or importlib.util.find_spec("paddle") is None:
        return {"state": "unavailable", "label": "Not installed",
                "reason": "PaddleOCR is not installed on the server."}
    models_dir = _paddlex_models_dir()
    present = {p.name for p in models_dir.iterdir() if p.is_dir()} if models_dir.is_dir() else set()
    cfg = ocr.engine_config(ocr.default_language())
    needed_det = cfg.get("text_detection_model_name")
    needed_rec = cfg.get("text_recognition_model_name")
    missing = []
    # With a language-based default PaddleOCR picks the model names itself, so accept any det/rec model.
    has_det = needed_det in present if needed_det else any(n.endswith("_det") for n in present)
    has_rec = needed_rec in present if needed_rec else any(n.endswith("_rec") for n in present)
    if not has_det:
        missing.append("text detection")
    if not has_rec:
        missing.append("text recognition")
    if cfg.get("use_doc_orientation_classify") and "PP-LCNet_x1_0_doc_ori" not in present:
        missing.append("page orientation")
    loaded = bool(ocr._engines)
    if missing:
        return {"state": "unavailable", "label": "Models missing",
                "reason": f"OCR model files not found ({', '.join(missing)}). They are downloaded on first use, "
                          "which needs network access once.", "loaded": loaded}
    return {
        "state": "ready", "label": "Ready", "loaded": loaded,
        "detail": ("OCR engine loaded in this server process" if loaded
                   else "Model files present; engine loads on first use"),
        "language": ocr.default_language(), "profile": getattr(settings, "OCR_MODEL_PROFILE", "server"),
    }


def model_health(ollama):
    from chat.model_registry import list_models
    from .usage import last_success_by_model

    last_ok = last_success_by_model()
    out = []
    for m in list_models():
        item = {
            "id": m.id, "name": m.name, "model": m.ollama_name, "capability": m.capability,
            "capability_label": CAPABILITY_LABELS.get(m.capability, m.capability),
            "last_success": last_ok.get(m.ollama_name),
        }
        if ollama["state"] != "ready":
            item.update(state="unavailable", label="Unavailable",
                        reason="The local Ollama service is not reachable.")
        elif m.ollama_name not in ollama["installed"]:
            item.update(state="unavailable", label="Unavailable",
                        reason="Model is not available through the local Ollama service.")
        else:
            loaded = ollama["loaded"].get(m.ollama_name)
            item.update(state="ready", label="Ready", size_bytes=ollama["installed"][m.ollama_name],
                        loaded=bool(loaded), vram_bytes=(loaded or {}).get("size_vram"))
        out.append(item)
    return out


def full_status():
    ollama = ollama_status()
    status = {
        "checked_at": timezone.now(),
        "services": {
            "backend": {"state": "ready", "label": "Online"},  # this response is the proof
            "ollama": {k: v for k, v in ollama.items() if k not in ("installed", "loaded")},
            "ocr": ocr_status(),
        },
        "models": model_health(ollama),
    }
    if ollama["state"] == "ready":
        status["services"]["ollama"]["loaded_models"] = [
            {"model": tag, "vram_bytes": info["size_vram"]} for tag, info in ollama["loaded"].items()
        ]
    return status
