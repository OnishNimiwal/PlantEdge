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

from chat.model_manager import generate_response, ModelManagerError
from chat.router import route_model, ROUTE_TARGETS, REASON_GENERAL, REASON_VISION
from chat.model_registry import get_model

logger = logging.getLogger(__name__)

# Large images exhaust the 8 GB GPU in the vision model, so render at most this size.
VISION_MAX_SIDE = 1024


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
        zoom = min(VISION_MAX_SIDE / max(page.rect.width, page.rect.height), 3.0)
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
    decision = route_model(question)
    images = None
    if decision["reason"] == REASON_VISION:
        image = document_image_b64(document)
        images = [image] if image else None
        if images is None:
            # Nothing visual to look at (e.g. TXT) -> fall back to text reasoning.
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
        prompt = (
            f"You are an on-premise local AI assistant analyzing the document '{document.original_name}'.\n"
            "Answer the user's question thoroughly and accurately based on the provided document content.\n"
            "If the answer cannot be determined from the document, clearly mention that.\n"
            f"{_ocr_note(document)}\n"
            "=== DOCUMENT CONTENT ===\n"
            f"{document.extracted_text}\n"
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
        "routing": {"mode": "auto", "reason": decision["reason"]},
    }


def summarize_document(document) -> dict:
    """
    Structured summary with the general reasoning model (qwen3).
    Returns {"summary", "model", "ollama_model", "routing"}.
    """
    model = get_model(ROUTE_TARGETS[REASON_GENERAL])
    prompt = (
        f"You are an on-premise local AI assistant analyzing the document '{document.original_name}'.\n"
        "Generate a structured, professional summary of this document.\n"
        "Include:\n"
        "1. Executive Overview\n"
        "2. Key Points & Findings\n"
        "3. Important Details & Conclusions\n"
        f"{_ocr_note(document)}\n"
        "=== DOCUMENT CONTENT ===\n"
        f"{document.extracted_text}\n"
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
    }
