"""
Basic deterministic model router (first prototype).

Model *selection* lives here; model *execution* lives in model_manager.py.
Replace route_model() with a smarter implementation later without touching
the views or the ModelManager - keep the same return shape.

No LLM is used for routing: plain keyword matching on whole words/phrases.
"""

import logging
import re

from .model_registry import get_model

logger = logging.getLogger(__name__)

REASON_CODING = "coding"
REASON_VISION = "vision"
REASON_GENERAL = "general_reasoning"

# Routing reason -> model id in MODEL_REGISTRY
ROUTE_TARGETS = {
    REASON_CODING: "qwen-coder",
    REASON_VISION: "qwen-vl",
    REASON_GENERAL: "qwen3",
}

CODING_KEYWORDS = (
    "code", "codes", "coding", "python", "c++", "java", "javascript",
    "function", "functions", "class", "classes", "debug", "debugging",
    "error", "errors", "algorithm", "algorithms", "program", "programs",
    "programming", "sql", "django", "react",
)

VISION_KEYWORDS = (
    "image", "images", "photo", "photos", "photograph", "photographs",
    "picture", "pictures", "scanned", "scanned document", "scanned pdf",
    "drawing", "drawings", "diagram", "diagrams", "p&id", "p&ids",
    "handwritten", "handwritten document", "visual inspection", "ocr",
    "image understanding",
)


def _compile(keywords):
    # Custom boundaries instead of \b so that "c++" and "p&id" match, while
    # "class" does not match inside "classify".
    alternatives = "|".join(
        re.escape(k) for k in sorted(keywords, key=len, reverse=True)
    )
    return re.compile(rf"(?<![\w&+])(?:{alternatives})(?![\w&+])", re.IGNORECASE)


_CODING_RE = _compile(CODING_KEYWORDS)
_VISION_RE = _compile(VISION_KEYWORDS)


def _matches(pattern, text):
    return sorted({m.group(0).lower() for m in pattern.finditer(text)})


def route_model(message: str, has_images: bool = False) -> dict:
    """
    Choose a local model for a request.

    Rules, in order:
      1. An attached image always routes to the vision model.
      2. Otherwise the category (coding / vision) with more distinct keyword
         hits wins; a tie goes to coding.
      3. No hits -> general reasoning model.

    Returns {"model": <ollama tag>, "model_id": <registry id>,
             "reason": "coding" | "vision" | "general_reasoning",
             "matched": [keywords that triggered the decision]}.
    """
    message = message or ""
    coding_hits = _matches(_CODING_RE, message)
    vision_hits = _matches(_VISION_RE, message)

    if has_images:
        reason, matched = REASON_VISION, ["<attached image>"] + vision_hits
    elif coding_hits and len(coding_hits) >= len(vision_hits):
        reason, matched = REASON_CODING, coding_hits
    elif vision_hits:
        reason, matched = REASON_VISION, vision_hits
    else:
        reason, matched = REASON_GENERAL, []

    model = get_model(ROUTE_TARGETS[reason])
    # Keywords come from the fixed lists above, so logging them leaks no prompt content.
    logger.info(
        "Routing decision: reason=%s model=%s matched=%s", reason, model.id, matched
    )
    return {
        "model": model.ollama_name,
        "model_id": model.id,
        "reason": reason,
        "matched": matched,
    }
