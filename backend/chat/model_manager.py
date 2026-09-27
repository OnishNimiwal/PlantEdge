"""
ModelManager: the single place where Django talks to the local Ollama server.

All inference goes Django -> local Ollama -> local model. There is no external
or cloud fallback. Model loading/unloading is left to Ollama's scheduler, which
evicts idle models when a new one does not fit in VRAM, so the three models are
used sequentially rather than held in GPU memory simultaneously.
"""

import logging
import time

import requests
from django.conf import settings

from .model_registry import get_model, get_default_model_id

logger = logging.getLogger(__name__)


class ModelManagerError(Exception):
    """Base error. `public_message` is safe to show to API clients."""

    public_message = "Local AI request failed."


class ModelUnavailableError(ModelManagerError):
    public_message = "Local AI server is unavailable."


class ModelTimeoutError(ModelManagerError):
    public_message = "Local AI model timed out. The model may still be loading; please try again."


class ModelNotInstalledError(ModelManagerError):
    public_message = "The selected model is not installed on the local Ollama server."


class ModelRequestError(ModelManagerError):
    public_message = "The local AI model failed to process the request."


class ModelManager:
    def __init__(self, base_url=None, timeout=None):
        self.base_url = (base_url or settings.OLLAMA_URL).rstrip("/")
        self.timeout = timeout or getattr(settings, "OLLAMA_TIMEOUT", 300)

    def generate(self, model_id=None, prompt="", images=None) -> dict:
        """
        Run a single non-streaming generation on a registered local model.

        `images` is an optional list of base64-encoded images (multimodal models only).
        Returns {"response", "model", "ollama_model", "duration_ms"}.
        Raises UnknownModelError or a ModelManagerError subclass.
        """
        model = get_model(model_id or get_default_model_id())
        payload = {
            "model": model.ollama_name,
            "prompt": prompt,
            "stream": False,
        }
        if images:
            if not model.supports_images:
                raise ModelRequestError(f"Model '{model.id}' does not accept images.")
            payload["images"] = images

        # Log metadata only - never prompt or image contents.
        logger.info(
            "Inference start: model=%s ollama_model=%s prompt_chars=%d images=%d",
            model.id, model.ollama_name, len(prompt), len(images or []),
        )
        started = time.monotonic()

        def elapsed_ms():
            return int((time.monotonic() - started) * 1000)

        try:
            response = requests.post(
                f"{self.base_url}/api/generate", json=payload, timeout=self.timeout
            )
        except requests.exceptions.Timeout as exc:
            logger.warning("Inference timeout: model=%s after %dms", model.id, elapsed_ms())
            raise ModelTimeoutError() from exc
        except requests.exceptions.RequestException as exc:
            logger.error(
                "Inference failed: model=%s Ollama unreachable (%s)",
                model.id, exc.__class__.__name__,
            )
            raise ModelUnavailableError() from exc

        if response.status_code == 404:
            logger.error(
                "Inference failed: model=%s ollama_model=%s not installed in Ollama",
                model.id, model.ollama_name,
            )
            raise ModelNotInstalledError()

        try:
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as exc:
            logger.error(
                "Inference failed: model=%s HTTP %s", model.id, response.status_code
            )
            raise ModelRequestError() from exc
        except ValueError as exc:
            logger.error("Inference failed: model=%s invalid JSON from Ollama", model.id)
            raise ModelRequestError() from exc

        duration = elapsed_ms()
        logger.info(
            "Inference success: model=%s ollama_model=%s duration_ms=%d eval_tokens=%s",
            model.id, model.ollama_name, duration, data.get("eval_count"),
        )
        return {
            "response": (data.get("response") or "").strip(),
            "model": model.id,
            "ollama_model": model.ollama_name,
            "duration_ms": duration,
        }
