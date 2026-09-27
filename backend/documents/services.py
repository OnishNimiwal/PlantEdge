"""
Document reasoning services.

Reuses the chat layers instead of calling Ollama directly:
    question -> chat.router.route_model()          (WHICH model)
             -> chat.model_manager.generate_response() (HOW: local Ollama only)

Text questions get the extracted (text-layer or OCR) text as context.
Questions that need visual understanding are sent to the vision model together
with the document image (page 1 for PDFs) instead of the OCR text.
"""

import base64
import logging

import pymupdf

from django.conf import settings

from chat.model_manager import (
    generate_response, ModelManagerError, prompt_budget_tokens, CHARS_PER_TOKEN,
)
from chat.router import route_model, ROUTE_TARGETS, REASON_GENERAL, REASON_VISION
from chat.model_registry import get_model

logger = logging.getLogger(__name__)


class OllamaServiceError(Exception):
    """Raised when the local model layer fails. str(exc) is safe to show to clients."""
    pass


def _ocr_note(document) -> str:
    if document.extraction_method in ("ocr", "text+ocr"):
        return (
            "Note: some or all of this text was produced by local OCR from a scanned "
            "image and may contain recognition errors.\n"
        )
    return ""


def fit_to_context(text: str, model_tag: str, reserved_chars: int) -> tuple:
    """
    Trim document text so the whole prompt fits the model's context window.
    (Ollama silently halves prompts that overflow num_ctx, dropping the instructions.)
    Returns (text, info) where info reports how much of the document the model saw.
    """
    budget = int(prompt_budget_tokens(get_model(model_tag)) * CHARS_PER_TOKEN) - reserved_chars
    budget = max(budget, 1000)
    info = {"document_chars": len(text), "context_chars_used": min(len(text), budget),
            "context_truncated": len(text) > budget}
    if info["context_truncated"]:
        text = (
            text[:budget]
            + f"\n[... document continues: only the first {budget:,} of {len(text):,} characters "
            "fit in the model context window ...]"
        )
    return text, info


def document_image_b64(document):
    """
    Render the document (image file, or page 1 of a PDF) as a PNG no larger than
    VISION_MAX_SIDE, base64-encoded. Returns None for documents without visuals.
    """
    if document.file_type not in ("PDF", "PNG", "JPG") or not document.file:
        return None
    document.file.open("rb")
    try:
        data = document.file.read()
    finally:
        document.file.close()
    filetype = {"PDF": "pdf", "PNG": "png", "JPG": "jpeg"}[document.file_type]
    with pymupdf.open(stream=data, filetype=filetype) as doc:
        page = doc[0]
        # Large images exhaust the 8 GB GPU in the vision model, so render at most this size.
        zoom = min(settings.VISION_MAX_SIDE / max(page.rect.width, page.rect.height), 3.0)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        return base64.b64encode(pix.tobytes("png")).decode()


def _run(model: str, prompt: str, images=None) -> dict:
    try:
        return generate_response(model, prompt, images=images)
    except ModelManagerError as exc:
        raise OllamaServiceError(exc.public_message) from exc


def ask_document_question(document, question: str) -> dict:
    """
    Answer a question about a document using the routed local model.
    Returns {"answer", "model", "ollama_model", "routing"}.
    """
    has_visual = document.file_type in ("PDF", "PNG", "JPG") and bool(document.file)
    decision = route_model(question, context={"image_available": has_visual})
    images = None
    context_info = {"document_chars": len(document.extracted_text), "context_chars_used": 0,
                    "context_truncated": False}
    if decision["requires_image"]:
        # e.g. "describe this image" on a TXT document: no visual, use the text.
        decision = route_model("")
    elif decision["reason"] == REASON_VISION:
        image = document_image_b64(document)
        images = [image] if image else None
        if images is None:
            # Nothing visual to look at -> answer from the text instead.
            decision = route_model("")

    if images:
        prompt = (
            f"You are an on-premise local AI assistant. The attached image is the document "
            f"'{document.original_name}'"
            f"{' (page 1)' if document.file_type == 'PDF' else ''}.\n"
            "Answer the user's question based on what you can see in the image.\n\n"
            f"USER QUESTION: {question}\n\nANSWER:"
        )
    else:
        doc_text, context_info = fit_to_context(
            document.extracted_text, decision["model"], reserved_chars=1500 + len(question)
        )
        prompt = (
            f"You are an on-premise local AI assistant analyzing the document '{document.original_name}'.\n"
            "Answer the user's question thoroughly and accurately based on the provided document content.\n"
            "If the answer cannot be determined from the document, clearly mention that.\n"
            f"{_ocr_note(document)}\n"
            "=== DOCUMENT CONTENT ===\n"
            f"{doc_text}\n"
            "=== END DOCUMENT CONTENT ===\n\n"
            f"USER QUESTION: {question}\n\n"
            "ANSWER:"
        )

    logger.info(
        "Document question: doc_id=%s method=%s reason=%s model=%s with_image=%s",
        document.id, document.extraction_method, decision["reason"], decision["model"], bool(images),
    )
    result = _run(decision["model"], prompt, images=images)
    return {
        "answer": result["response"],
        "model": result["model"],
        "ollama_model": result["ollama_model"],
        "routing": {"mode": "auto", "reason": decision["reason"], "explanation": decision["explanation"]},
        "context": context_info,
    }


def summarize_document(document) -> dict:
    """
    Structured summary with the general reasoning model (qwen3).
    Returns {"summary", "model", "ollama_model", "routing"}.
    """
    model = get_model(ROUTE_TARGETS[REASON_GENERAL])
    doc_text, context_info = fit_to_context(document.extracted_text, model.id, reserved_chars=1500)
    prompt = (
        f"You are an on-premise local AI assistant analyzing the document '{document.original_name}'.\n"
        "Generate a structured, professional summary of this document.\n"
        "Include:\n"
        "1. Executive Overview\n"
        "2. Key Points & Findings\n"
        "3. Important Details & Conclusions\n"
        f"{_ocr_note(document)}\n"
        "=== DOCUMENT CONTENT ===\n"
        f"{doc_text}\n"
        "=== END DOCUMENT CONTENT ===\n\n"
        "EXECUTIVE SUMMARY:"
    )
    logger.info(
        "Document summary: doc_id=%s method=%s model=%s",
        document.id, document.extraction_method, model.ollama_name,
    )
    result = _run(model.ollama_name, prompt)
    return {
        "summary": result["response"],
        "model": result["model"],
        "ollama_model": result["ollama_model"],
        "routing": {"mode": "fixed", "reason": REASON_GENERAL},
        "context": context_info,
    }
