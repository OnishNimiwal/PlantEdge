"""
Deterministic model router.

Model *selection* lives here; model *execution* lives in model_manager.py.
Rule data lives in routing_rules.py. No LLM, no embeddings, no HTTP.

Decision order (first match wins) - see route_model() for the reasoning:
  1. Image attached to this message               -> vision  (only the VL model can see it)
  2. Image available from context, and the message refers to it
     (visual target, visual property, or a follow-up to a vision turn)
                                                  -> vision
  3. Explicit visual target but no image anywhere -> vision + requires_image
                                                     (caller asks the user to attach one)
  4. Coding signal                                -> coding
  5. Otherwise                                    -> general_reasoning
"""

import logging
import re

from . import routing_rules as rules
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


def _compile(patterns):
    return [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in patterns]


_CODING_STRONG = _compile(rules.CODING_STRONG)
_CODING_WEAK = _compile(rules.CODING_WEAK)
_CODE_ACTIONS = re.compile(rules.CODE_ACTIONS, re.IGNORECASE)
_CODING_NEGATIVE = _compile(rules.CODING_NEGATIVE)
_VISION_TARGET = _compile(rules.VISION_TARGET)
_VISION_ACTIONS = _compile(rules.VISION_ACTIONS)
_VISUAL_PROPERTIES = _compile(rules.VISUAL_PROPERTIES)
_FOLLOWUP = _compile(rules.FOLLOWUP_MARKERS)
_TEXT_EXTRACTION = _compile(rules.TEXT_EXTRACTION)


def _hits(patterns, text):
    found = []
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            found.append(match.group(0).strip().lower())
    return found


def _strip_negatives(text):
    """Blank out phrases such as 'training program' or 'human error'."""
    removed = []
    for pattern in _CODING_NEGATIVE:
        for match in pattern.finditer(text):
            removed.append(match.group(0).lower())
        text = pattern.sub(" ", text)
    return text, removed


def analyze(message: str) -> dict:
    """Intent signals found in a message (pure function, no context)."""
    message = message or ""
    cleaned, negated = _strip_negatives(message)
    strong = _hits(_CODING_STRONG, cleaned)
    weak = _hits(_CODING_WEAK, cleaned)
    code_action = bool(_CODE_ACTIONS.search(cleaned))
    coding = bool(strong) or len(weak) >= 2 or (bool(weak) and code_action)
    return {
        "coding": coding,
        "coding_hits": strong + weak,
        "negated": negated,
        "vision_target": _hits(_VISION_TARGET, message) + _hits(_VISION_ACTIONS, message),
        "visual_properties": _hits(_VISUAL_PROPERTIES, message),
        "followup": _hits(_FOLLOWUP, message),
        "text_extraction": _hits(_TEXT_EXTRACTION, message),
    }


def route_model(message: str, has_images: bool = False, context: dict = None) -> dict:
    """
    Choose a local model for a request.

    `has_images`: images are attached to this message.
    `context` (optional): {"image_available": bool, "last_reason": str} - an image
    from an earlier turn / the open document that could be re-sent, and the
    routing reason of the previous turn.

    Returns {"model", "model_id", "reason", "requires_image", "explanation",
             "signals", "matched"}.
    """
    context = context or {}
    s = analyze(message)
    image_available = bool(context.get("image_available"))
    last_reason = context.get("last_reason")
    vision_words = s["vision_target"] or s["text_extraction"]
    requires_image = False

    if has_images:
        reason = REASON_VISION
        explanation = "image attached"
        if s["coding"]:
            # Mixed vision + coding: the coder cannot see, so the VL model answers
            # both parts in one step (a VL -> coder chain is future work).
            explanation = "image attached; mixed vision+coding request handled by the vision model"
    elif image_available and (vision_words or (s["visual_properties"] and not s["coding"])):
        reason = REASON_VISION
        explanation = "refers to an image from this conversation/document"
    elif image_available and last_reason == REASON_VISION and s["followup"] and not s["coding"]:
        reason = REASON_VISION
        explanation = "follow-up question to a previous image"
    elif vision_words and not image_available:
        reason = REASON_VISION
        requires_image = True
        explanation = "refers to an image, but none is attached"
    elif s["coding"]:
        reason = REASON_CODING
        explanation = "coding request"
    else:
        reason = REASON_GENERAL
        explanation = "no coding or visual-target signal"

    model = get_model(ROUTE_TARGETS[reason])
    matched = {
        REASON_CODING: s["coding_hits"],
        REASON_VISION: s["vision_target"] + s["text_extraction"] + s["visual_properties"],
        REASON_GENERAL: [],
    }[reason]
    # Matches come from fixed rule patterns (short phrases), not free-form prompt text.
    logger.info(
        "Routing decision: reason=%s model=%s requires_image=%s explanation=%r",
        reason, model.id, requires_image, explanation,
    )
    return {
        "model": model.ollama_name,
        "model_id": model.id,
        "reason": reason,
        "requires_image": requires_image,
        "explanation": explanation,
        "signals": s,
        "matched": (["<attached image>"] if has_images else []) + matched,
    }
