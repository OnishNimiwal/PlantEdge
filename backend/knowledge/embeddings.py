"""
Local text embeddings through the local Ollama server (/api/embed).

Same network rules as the chat models: the request only goes to OLLAMA_URL after
chat.model_manager.ensure_local_endpoint() accepts it, through a session that
ignores proxy variables. Nothing is sent to an external embedding service.

EMBEDDING_DEVICE=cpu (default) asks Ollama to keep the embedding model off the GPU
(num_gpu=0), so indexing and query embedding never evict the chat model from the
8 GB GPU and do not take a slot in the GPU request queue.
"""

import logging
import time

from django.conf import settings

from chat.model_manager import _session, _inflight_begin, _inflight_end, ensure_local_endpoint

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """The local embedding model could not embed the text. str(exc) is safe to show."""


def model_name():
    return settings.EMBEDDING_MODEL


def _on_gpu():
    return getattr(settings, "EMBEDDING_DEVICE", "cpu") == "gpu"


def _request(texts):
    payload = {
        "model": model_name(),
        "input": texts,
        "truncate": True,
        "keep_alive": getattr(settings, "EMBEDDING_KEEP_ALIVE", "30m"),
    }
    if not _on_gpu():
        payload["options"] = {"num_gpu": 0}
    ensure_local_endpoint(settings.OLLAMA_URL)
    try:
        resp = _session().post(f"{settings.OLLAMA_URL}/api/embed", json=payload,
                               timeout=getattr(settings, "EMBEDDING_TIMEOUT", 120), allow_redirects=False)
    except Exception as exc:
        raise EmbeddingError("The local embedding model is not reachable.") from exc
    if resp.status_code == 404:
        raise EmbeddingError(f"Embedding model '{model_name()}' is not installed (ollama pull {model_name()}).")
    if resp.status_code != 200:
        raise EmbeddingError(f"The local embedding model failed (HTTP {resp.status_code}).")
    vectors = resp.json().get("embeddings") or []
    if len(vectors) != len(texts):
        raise EmbeddingError("The local embedding model returned an unexpected result.")
    return vectors


def embed(texts):
    """Embed texts (documents / sections) in batches -> list of vectors."""
    texts = [t or " " for t in texts]
    if not texts:
        return []
    size = max(1, int(getattr(settings, "EMBEDDING_BATCH_SIZE", 16)))
    start, out = time.monotonic(), []
    if _on_gpu():
        _inflight_begin()  # share the GPU queue with the chat models
    try:
        for i in range(0, len(texts), size):
            out.extend(_request(texts[i:i + size]))
    finally:
        if _on_gpu():
            _inflight_end()
    logger.info("Embedded %d text(s) with %s in %.1fs", len(texts), model_name(), time.monotonic() - start)
    return out


def embed_query(question):
    """Embed a search query (with the instruction prefix for instruction-aware models)."""
    instruction = getattr(settings, "EMBEDDING_QUERY_INSTRUCTION", "")
    text = f"Instruct: {instruction}\nQuery: {question}" if instruction else question
    return embed([text])[0]
