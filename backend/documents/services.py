"""
Document reasoning services.

Reuses the chat layers instead of calling Ollama directly:
    question -> chat.router.route_model()          (WHICH model)
             -> chat.model_manager.generate_response() (HOW: local Ollama only)

Text questions get the extracted (text-layer or OCR) text as context.
Questions that need visual understanding are sent to the vision model together
with the document image (page 1 for PDFs) instead of the OCR text.
"""

import logging



from chat.model_manager import (
    generate_response, ModelManagerError, prompt_budget_tokens, CHARS_PER_TOKEN,
)
from chat.router import route_model, ROUTE_TARGETS, REASON_GENERAL, REASON_VISION
from chat.model_registry import get_model
from chat import context as chat_context
from . import processing

logger = logging.getLogger(__name__)

FORMAT_HINT = (
    "Format the answer in GitHub-flavored Markdown: real Markdown tables for tabular data "
    "(never inside code blocks), fenced code blocks only for code."
)


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


def _run(model: str, prompt: str, images=None) -> dict:
    try:
        return generate_response(model, prompt, images=images)
    except ModelManagerError as exc:
        raise OllamaServiceError(exc.public_message) from exc


class NothingToRegenerate(Exception):
    pass


def prepare_document_question(document, question=None, conversation_id=None, regenerate=False) -> dict:
    """
    Routing + prompt building for a document question (shared by the JSON and
    streaming endpoints). With regenerate=True the conversation's last question is
    re-asked and its old answer replaced once the new one is recorded.
    """
    replaced_ids = ()
    if regenerate:
        conv = chat_context.load(conversation_id, document=document, create=False)
        last = chat_context.last_turn(conv) if conv else None
        if not last:
            raise NothingToRegenerate()
        question, replaced_ids = last["message"], last["ids"]
    else:
        conv = chat_context.load(conversation_id, document=document)
    has_visual = document.file_type in ("PDF", "PNG", "JPG") and bool(document.file)
    signals = chat_context.signals(conv, exclude_ids=replaced_ids)
    decision = route_model(question, context={**signals, "image_available": has_visual})
    images = None
    vision_pages = []
    context_info = {"document_chars": len(document.extracted_text), "context_chars_used": 0,
                    "context_truncated": False}
    if decision["requires_image"]:
        # e.g. "describe this image" on a TXT document: no visual, use the text.
        decision = route_model("")
    elif decision["reason"] == REASON_VISION:
        page_count = document.page_count or 1
        vision_pages = processing.requested_pages(question, page_count) if document.file_type == "PDF" else [1]
        images = processing.document_images_b64(document, vision_pages) or None
        if images is None:
            # Nothing visual to look at -> answer from the text instead.
            decision = route_model("")
            vision_pages = []

    if images:
        where = (
            f"page{'s' if len(vision_pages) > 1 else ''} {', '.join(map(str, vision_pages))} of "
            f"{document.page_count or 1} of the PDF" if document.file_type == "PDF" else "the image"
        )
        # Text + visual: give the vision model the extracted text too (helps read labels).
        excerpt = document.extracted_text[:3000]
        system = (
            f"You are an on-premise local AI assistant. The attached image(s) show {where} "
            f"'{document.original_name}'. Answer the user's questions based on what you can see; "
            "only the attached pages are visible to you. " + FORMAT_HINT + "\n"
            "Text extracted from the document (may help read labels; may contain OCR errors):\n"
            f"{excerpt}"
        )
    else:
        # Leave a quarter of the budget for conversation history.
        history_reserve = int(prompt_budget_tokens(get_model(decision["model"])) * CHARS_PER_TOKEN) // 4
        doc_text, context_info = fit_to_context(
            document.extracted_text, decision["model"],
            reserved_chars=1500 + len(question) + history_reserve,
        )
        system = (
            f"You are an on-premise local AI assistant analyzing the document '{document.original_name}'.\n"
            "Answer the user's questions thoroughly and accurately based on the provided document content.\n"
            "If the answer cannot be determined from the document, clearly mention that.\n"
            f"{FORMAT_HINT}\n"
            f"{_ocr_note(document)}\n"
            "=== DOCUMENT CONTENT ===\n"
            f"{doc_text}\n"
            "=== END DOCUMENT CONTENT ==="
        )

    messages, history_info = chat_context.build_messages(
        conv, question, decision["model"], new_images=images, system=system, exclude_ids=replaced_ids,
    )
    logger.info(
        "Document question: doc_id=%s method=%s reason=%s model=%s with_image=%s history=%d",
        document.id, document.extraction_method, decision["reason"], decision["model"], bool(images),
        history_info["history_messages_used"],
    )
    return {
        "conv": conv, "question": question, "decision": decision, "messages": messages,
        "replaced_ids": replaced_ids, "document": document,
        "meta": {
            "routing": {"mode": "auto", "reason": decision["reason"], "explanation": decision["explanation"]},
            "context": {**context_info, **history_info},
            "conversation_id": str(conv.id),
            "ollama_model": decision["model"],
            "vision_pages": vision_pages,
            "page_count": document.page_count,
        },
    }


def finish_document_question(prepared, result) -> dict:
    """Record the exchange and build the response body."""
    chat_context.discard(prepared["replaced_ids"])
    # The document image is re-rendered on demand, so it is not stored as an attachment.
    chat_context.record_turn(prepared["conv"], prepared["question"], result["response"],
                             model_tag=result["ollama_model"], reason=prepared["decision"]["reason"])
    return {
        "answer": result["response"],
        "model": result["model"],
        "ollama_model": result["ollama_model"],
        **prepared["meta"],
    }


def ask_document_question(document, question=None, conversation_id=None, regenerate=False) -> dict:
    """
    Answer a question about a document using the routed local model, with the
    document's conversation history (backend-held, see chat/context.py).
    Returns {"answer", "model", "ollama_model", "routing", "context", "conversation_id", ...}.
    """
    prepared = prepare_document_question(document, question, conversation_id, regenerate)
    try:
        result = generate_response(prepared["decision"]["model"], messages=prepared["messages"])
    except ModelManagerError as exc:
        raise OllamaServiceError(exc.public_message) from exc
    return finish_document_question(prepared, result)


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
        f"{FORMAT_HINT}\n"
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
