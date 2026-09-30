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


GPU_FIELDS = [
    "name", "driver_version", "memory.used", "memory.total", "utilization.gpu", "temperature.gpu",
    "power.draw", "power.limit", "power.default_limit", "clocks.sm", "clocks.max.sm",
    "clocks_event_reasons.sw_power_cap", "clocks_event_reasons.sw_thermal_slowdown",
    "clocks_event_reasons.hw_slowdown", "pstate",
]


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _power_source():
    """'ac' | 'battery' | None (desktop / unknown), from /sys/class/power_supply."""
    base = Path("/sys/class/power_supply")
    if not base.is_dir():
        return None
    mains = [p for p in base.iterdir() if (p / "type").is_file() and (p / "type").read_text().strip() == "Mains"]
    if not mains:
        return None
    online = any((p / "online").is_file() and (p / "online").read_text().strip() == "1" for p in mains)
    return "ac" if online else "battery"


def gpu_status():
    """
    NVIDIA GPU state via `nvidia-smi` (a local query, no GPU work) plus laptop power source.
    Flags conditions that make inference much slower, e.g. running on battery, where the
    GPU power limit drops (measured: 55 W -> 10 W, ~10x slower answers).
    """
    import shutil
    import subprocess
    if not shutil.which("nvidia-smi"):
        return {"state": "unavailable", "label": "Not detected", "reason": "No NVIDIA GPU tools found on the server."}
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={','.join(GPU_FIELDS)}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=HEALTH_TIMEOUT,
        ).stdout.strip().splitlines()[0]
    except Exception as exc:
        logger.warning("GPU check failed: %s", exc.__class__.__name__)
        return {"state": "unavailable", "label": "Unavailable", "reason": "The GPU status could not be read."}
    values = dict(zip(GPU_FIELDS, [v.strip() for v in out.split(",")]))
    info = {
        "name": values.get("name"), "driver": values.get("driver_version"),
        "memory_used_mb": _num(values.get("memory.used")), "memory_total_mb": _num(values.get("memory.total")),
        "utilization": _num(values.get("utilization.gpu")), "temperature_c": _num(values.get("temperature.gpu")),
        "power_draw_w": _num(values.get("power.draw")), "power_limit_w": _num(values.get("power.limit")),
        "power_default_w": _num(values.get("power.default_limit")),
        "clock_mhz": _num(values.get("clocks.sm")), "clock_max_mhz": _num(values.get("clocks.max.sm")),
        "pstate": values.get("pstate"), "power_source": _power_source(),
    }
    warnings = []
    if info["power_source"] == "battery":
        warnings.append("Running on battery: the laptop limits GPU power, so answers are much slower. "
                        "Connect the charger.")
    if info["power_limit_w"] and info["power_default_w"] and info["power_limit_w"] < 0.5 * info["power_default_w"]:
        warnings.append(f"GPU power limited to {info['power_limit_w']:.0f} W "
                        f"(normal {info['power_default_w']:.0f} W).")
    if values.get("clocks_event_reasons.sw_power_cap") == "Active" and (info["utilization"] or 0) > 50:
        warnings.append("The GPU is being power-capped while busy.")
    if "Active" in (values.get("clocks_event_reasons.sw_thermal_slowdown"), values.get("clocks_event_reasons.hw_slowdown")):
        warnings.append("The GPU is slowing down to control temperature or power.")
    if (info["temperature_c"] or 0) >= 87:
        warnings.append(f"GPU temperature is high ({info['temperature_c']:.0f} °C).")
    state, label = ("degraded", "Limited") if warnings else ("ready", "Ready")
    return {"state": state, "label": label, "warnings": warnings, **info}


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
            "gpu": gpu_status(),
        },
        "models": model_health(ollama),
    }
    if ollama["state"] == "ready":
        status["services"]["ollama"]["loaded_models"] = [
            {"model": tag, "vram_bytes": info["size_vram"]} for tag, info in ollama["loaded"].items()
        ]
    return status
