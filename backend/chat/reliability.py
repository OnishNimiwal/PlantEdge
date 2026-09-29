"""
Response reliability layer (hallucination *reduction*, not elimination).

1. Instructions - one shared core plus a short addition per mode, composed into
   the system message by the chat view and the document services:
       general   normal knowledge answers, uncertainty marked
       document  answer only from the supplied document text
       image_text answer only from OCR text of an attached image
       vision    describe what is observable; separate observed / inferred / unknown
       coding    never claim code was executed or tested
2. Basis - a deterministic indicator of what an answer was based on (document,
   image, OCR text, general knowledge, generated code). It is derived from what
   was actually sent to the model, never from the model's own claims, and it
   does not mean the answer is correct.
3. "Cannot be determined" detection - a small fixed phrase list (no second
   model / LLM-as-judge) so grounded answers that report missing information
   get a warning indicator instead of a check mark.

Keep this module separate from routing: the router picks the model, this
module only shapes the instructions and labels the result.
"""

import re

from django.conf import settings

CORE = (
    "You are MRPL Local AI, an on-premise assistant for an industrial company. "
    "Accuracy is more important than appearing confident. "
    "Do not fabricate facts, numbers, names, measurements, components, references, citations or observations. "
    "If the available information is insufficient to answer, say so clearly instead of guessing. "
    "Distinguish observations from assumptions and inferences. "
    "If something is ambiguous, explain the ambiguity rather than picking an answer."
)

NOT_IN_DOCUMENT = "I could not find this information in the provided document."
NOT_IN_IMAGE = "This cannot be determined from the provided image."

MODES = {
    "general": (
        "Answer normally using your general knowledge; do not refuse ordinary questions. "
        "Mark uncertain points as uncertain instead of presenting them as fact, and do not invent "
        "specific statistics, dates, quotations, URLs or citations. If you do not know, say so."
    ),
    "document": (
        "Answer only from the supplied document content, not from general knowledge or assumptions. "
        "Do not fill gaps or invent missing values. "
        f"If the document does not contain the requested information, say exactly: \"{NOT_IN_DOCUMENT}\" "
        "and then, if helpful, mention what related information the document does contain. "
        "If you infer something that the document does not state directly, label it as an inference."
    ),
    "image_text": (
        "The user's image was converted to text with local OCR; answer only from that OCR text. "
        "OCR can misread characters, so point out values that look garbled instead of correcting them silently. "
        f"If the text does not contain the requested information, say exactly: \"{NOT_IN_DOCUMENT}\""
    ),
    "vision": (
        "Describe only what can actually be seen in the provided image(s). "
        "When describing or analysing an image, organise the answer under **Observed**, **Inferred** "
        "(only if you draw inferences) and **Cannot be determined** (only if relevant). "
        "For a short factual question about the image, answer directly. "
        "Never invent manufacturer names, exact models, measurements, capacities, certifications, "
        "serial numbers, dates, technical specifications, hidden objects or unreadable text. "
        f"If the image does not show the requested information, say exactly: \"{NOT_IN_IMAGE}\""
    ),
    "coding": (
        "You cannot run code: never say or imply that code was executed, tested, benchmarked or verified. "
        "Avoid claims such as \"this works perfectly\"; say what the code should do and, where relevant, "
        "state that you have not executed it and how the user can test it."
    ),
}

# Router reason -> reliability mode
REASON_MODE = {
    "general_reasoning": "general",
    "coding": "coding",
    "vision": "vision",
    "vision_ocr": "vision",
    "ocr_text": "image_text",
}
CAPABILITY_MODE = {"reasoning": "general", "coding": "coding", "vision": "vision"}


def enabled() -> bool:
    return bool(getattr(settings, "RELIABILITY_INSTRUCTIONS", True))


def mode_for(reason, model=None, has_images=False):
    if reason in REASON_MODE:
        return REASON_MODE[reason]
    if has_images:
        return "vision"
    return CAPABILITY_MODE.get(getattr(model, "capability", None), "general")


def instruction(mode) -> str:
    """Core + mode-specific reliability instruction ('' when disabled)."""
    if not enabled():
        return ""
    return f"{CORE}\n{MODES.get(mode, MODES['general'])}"


def system_prompt(mode, *parts) -> str:
    """Compose the system message: reliability instruction + any extra parts (formatting, context)."""
    return "\n\n".join(p for p in (instruction(mode), *parts) if p and p.strip())


# ---------------------------------------------------------------------------
# Basis indicator
# ---------------------------------------------------------------------------

_UNDETERMINED = [re.compile(p, re.IGNORECASE) for p in (
    r"could not find (?:this|that|the|any|such)? ?(?:information|value|detail|data)",
    r"(?:cannot|can't|can not|could not) be (?:determined|identified|verified|confirmed|read)",
    r"(?:is|are) not (?:specified|mentioned|stated|provided|given|included|listed|visible|legible|readable|shown)"
    r"(?: anywhere)? in the (?:provided |uploaded |attached |supplied )?(?:document|image|text|report|picture|photo|drawing)",
    r"the (?:provided |uploaded |attached |supplied )?(?:document|image|report|text|picture|photo) does not "
    r"(?:specify|mention|state|contain|include|provide|show|indicate)",
    r"(?:i do not|i don't|there is not|there isn't) (?:have )?enough information",
    r"not possible to determine",
)]

# Only the opening of an answer is checked, so a long answer that notes one
# missing detail in passing is not labelled "cannot be determined" as a whole.
_UNDETERMINED_WINDOW = 320

LABELS = {
    "document": "Based on uploaded document",
    "image": "Based on provided image",
    "image_text": "Based on text read from the provided image (OCR)",
    "general": "General AI response",
    "code": "Generated code — not executed",
}
UNDETERMINED_LABELS = {
    "document": "Not found in the provided document",
    "image": "Cannot be determined from the provided image",
    "image_text": "Not found in the text read from the image",
}


def reports_missing_information(text: str) -> bool:
    head = (text or "")[:_UNDETERMINED_WINDOW]
    return any(p.search(head) for p in _UNDETERMINED)


def basis(kind, response, detail=""):
    """
    {"type", "label", "detail", "undetermined"} describing what the answer was based on.
    Grounded kinds (document / image / image_text) switch to a warning label when the
    answer reports that the information is not available.
    """
    undetermined = kind in UNDETERMINED_LABELS and reports_missing_information(response)
    return {
        "type": kind,
        "label": UNDETERMINED_LABELS[kind] if undetermined else LABELS[kind],
        "detail": detail,
        "undetermined": undetermined,
    }


def chat_basis_kind(reason, sent_images, used_ocr, model=None):
    """Basis kind for a General Chat answer, from what was actually sent to the model."""
    if sent_images:
        return "image"
    if used_ocr:
        return "image_text"
    if reason == "coding" or (reason == "manual" and getattr(model, "capability", None) == "coding"):
        return "code"
    return "general"
