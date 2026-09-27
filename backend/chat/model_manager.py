"""
Model execution layer: the single place where Django talks to the local Ollama server.

The router (router.py) decides WHICH model to use; this module decides HOW to
talk to it. Entry point: generate_response(model, prompt, images=None).

All inference goes Django -> local Ollama -> local model. There is no external
or cloud fallback. Requests are refused unless OLLAMA_URL resolves to loopback,
or to a private-LAN address explicitly listed in OLLAMA_ALLOWED_HOSTS. This is a
network restriction on where prompts may be sent, not complete security. Model loading/unloading is left to Ollama's scheduler, which
evicts idle models when a new one does not fit in VRAM, so the three models are
used sequentially rather than held in GPU memory simultaneously.
"""

import ipaddress
import logging
import socket
import time
from urllib.parse import urlparse

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


class ModelResourceError(ModelManagerError):
    public_message = (
        "The local GPU ran out of memory for this request. "
        "Try a smaller image, fewer images, or a shorter message."
    )


class NonLocalEndpointError(ModelManagerError):
    public_message = "Local AI server is misconfigured."


# ---------------------------------------------------------------------------
# Local-only endpoint check
# ---------------------------------------------------------------------------

def _allowlist():
    entries = getattr(settings, "OLLAMA_ALLOWED_HOSTS", []) or []
    names, networks = set(), []
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            names.add(entry.lower())
    return names, networks


def _address_allowed(host: str, address: str, names, networks) -> bool:
    ip = ipaddress.ip_address(address)
    if ip.is_loopback:
        return True
    # Link-local (incl. 169.254.169.254 cloud metadata), multicast etc. are never allowed.
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return False
    if not ip.is_private:
        return False  # public addresses are refused even if listed
    return host.lower() in names or any(ip in net for net in networks)


def ensure_local_endpoint(base_url: str) -> None:
    """
    Refuse any Ollama URL that does not resolve to loopback, or to a private-LAN
    address that is explicitly allow-listed in OLLAMA_ALLOWED_HOSTS.
    """
    host = urlparse(base_url).hostname
    if not host:
        raise NonLocalEndpointError(f"Invalid OLLAMA_URL: {base_url!r}")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise ModelUnavailableError(f"Cannot resolve Ollama host {host!r}") from exc
    names, networks = _allowlist()
    if not addresses or not all(_address_allowed(host, a, names, networks) for a in addresses):
        logger.error("Refusing Ollama endpoint outside the local allow-list: host=%s", host)
        raise NonLocalEndpointError(f"Ollama host {host!r} is not an allowed local address")


# ---------------------------------------------------------------------------
# Context-window budget (Ollama silently halves prompts that overflow num_ctx)
# ---------------------------------------------------------------------------

CHARS_PER_TOKEN = 3.0        # conservative; measured ~2.75 for numeric text, ~4 for prose
TOKENS_PER_IMAGE = 1100      # measured for a 1024 px image on qwen2.5vl


def context_window(model) -> int:
    return int(getattr(settings, "OLLAMA_NUM_CTX", 8192))


def estimate_tokens(text: str = "", images: int = 0) -> int:
    return int(len(text or "") / CHARS_PER_TOKEN) + images * TOKENS_PER_IMAGE


def prompt_budget_tokens(model) -> int:
    """Tokens available for the prompt, leaving a quarter of the window for the answer."""
    return context_window(model) * 3 // 4


def _session():
    session = requests.Session()
    # Ignore HTTP(S)_PROXY env vars: a proxy could forward prompts off-premise.
    session.trust_env = False
    return session


class ModelManager:
    def __init__(self, base_url=None, timeout=None):
        self.base_url = (base_url or settings.OLLAMA_URL).rstrip("/")
        self.timeout = timeout or getattr(settings, "OLLAMA_TIMEOUT", 300)

    def _options(self, model) -> dict:
        extra = {"options": {"num_ctx": context_window(model)}}
        think = getattr(settings, "OLLAMA_THINK", None)
        if model.supports_thinking and think is not None:
            extra["think"] = think
        return extra

    def generate(self, model_id=None, prompt="", images=None) -> dict:
        """
        Run a single non-streaming generation on a registered local model.

        `model_id` may be a registry id ("qwen-coder") or an Ollama tag
        ("qwen2.5-coder:7b"); omitted -> DEFAULT_CHAT_MODEL.
        `images` is an optional list of base64-encoded images (multimodal models only).
        Returns {"response", "model", "ollama_model", "duration_ms", "context_overflow"}.
        Raises UnknownModelError or a ModelManagerError subclass.
        """
        model = get_model(model_id or get_default_model_id())
        ensure_local_endpoint(self.base_url)
        payload = {
            "model": model.ollama_name,
            "prompt": prompt,
            "stream": False,
            **self._options(model),
        }
        if images:
            if not model.supports_images:
                raise ModelRequestError(f"Model '{model.id}' does not accept images.")
            payload["images"] = images
        data, duration = self._post(
            "/api/generate", payload, model, len(prompt), len(images or [])
        )
        return {
            "response": (data.get("response") or "").strip(),
            "model": model.id,
            "ollama_model": model.ollama_name,
            "duration_ms": duration,
            "context_overflow": estimate_tokens(prompt, len(images or [])) > context_window(model),
        }

    def chat(self, model_id, messages) -> dict:
        """
        Multi-turn generation via Ollama /api/chat.

        `messages`: [{"role": "system"|"user"|"assistant", "content": str,
                      "images": [base64, ...] (optional, multimodal models only)}]
        Returns the same shape as generate().
        """
        model = get_model(model_id or get_default_model_id())
        ensure_local_endpoint(self.base_url)
        image_count = sum(len(m.get("images") or []) for m in messages)
        if image_count and not model.supports_images:
            raise ModelRequestError(f"Model '{model.id}' does not accept images.")
        payload = {
            "model": model.ollama_name,
            "messages": messages,
            "stream": False,
            **self._options(model),
        }
        prompt_chars = sum(len(m.get("content") or "") for m in messages)
        data, duration = self._post("/api/chat", payload, model, prompt_chars, image_count)
        return {
            "response": ((data.get("message") or {}).get("content") or "").strip(),
            "model": model.id,
            "ollama_model": model.ollama_name,
            "duration_ms": duration,
            "context_overflow": (int(prompt_chars / CHARS_PER_TOKEN) + image_count * TOKENS_PER_IMAGE)
            > context_window(model),
        }

    def _post(self, endpoint, payload, model, prompt_chars, image_count):
        # Log metadata only - never prompt or image contents.
        estimated = int(prompt_chars / CHARS_PER_TOKEN) + image_count * TOKENS_PER_IMAGE
        logger.info(
            "Inference start: model=%s ollama_model=%s prompt_chars=%d images=%d num_ctx=%d think=%s",
            model.id, model.ollama_name, prompt_chars, image_count,
            payload["options"]["num_ctx"], payload.get("think", "default"),
        )
        if estimated > payload["options"]["num_ctx"]:
            logger.warning(
                "Prompt (~%d tokens) exceeds num_ctx=%d for model=%s; Ollama will truncate it",
                estimated, payload["options"]["num_ctx"], model.id,
            )
        started = time.monotonic()

        def elapsed_ms():
            return int((time.monotonic() - started) * 1000)

        try:
            response = _session().post(
                f"{self.base_url}{endpoint}", json=payload, timeout=self.timeout,
                allow_redirects=False,  # a redirect could bypass the local-only check
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
        if 300 <= response.status_code < 400:
            logger.error("Inference failed: model=%s Ollama replied with a redirect", model.id)
            raise NonLocalEndpointError()
        if response.status_code >= 500 and "out of memory" in (response.text or "").lower():
            logger.error("Inference failed: model=%s GPU out of memory", model.id)
            raise ModelResourceError()

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
            "Inference success: model=%s ollama_model=%s duration_ms=%d prompt_tokens=%s eval_tokens=%s",
            model.id, model.ollama_name, duration, data.get("prompt_eval_count"), data.get("eval_count"),
        )
        return data, duration


def generate_response(model: str, prompt: str = None, images=None, messages=None) -> dict:
    """
    Execution-layer entry point: run a request on the model chosen by the router.

    `model` is the router's Ollama tag (e.g. "qwen2.5-coder:7b") or a registry id.
    Either a single `prompt` (+ optional `images`) or a list of chat `messages`
    (conversation history built by chat/context.py).
    Returns {"response", "model", "ollama_model", "duration_ms", "context_overflow"}.
    """
    if messages is not None:
        return ModelManager().chat(model, messages)
    return ModelManager().generate(model, prompt or "", images=images)
