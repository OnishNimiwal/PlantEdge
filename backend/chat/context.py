"""
Conversation context manager.

Sits between the API views and the router / execution layer:

    request -> context.load() -> router (uses context signals)
            -> context.build_messages() -> execution layer (/api/chat)
            -> context.record_turn()

Keeps history bounded so it always fits the model's context window:
  - at most CONTEXT_MAX_MESSAGES earlier messages, newest first, within a char budget
  - images are only re-sent to the vision model, and only the most recent set
    (from the current message, or else the latest earlier message that had images)
  - text models see "[user attached N image(s)]" placeholders instead of images
"""

import base64
import logging
import uuid

from django.conf import settings
from django.core.files.base import ContentFile

from .model_manager import TOKENS_PER_IMAGE, prompt_budget_tokens, chars_per_token
from .model_registry import get_model
from .models import Conversation, ChatMessage, ChatAttachment

logger = logging.getLogger(__name__)


def _max_messages():
    return int(getattr(settings, "CONTEXT_MAX_MESSAGES", 12))


def _image_turns():
    # How many recent messages an earlier image stays "in scope" for follow-ups.
    return int(getattr(settings, "CONTEXT_IMAGE_TURNS", 8))


def load(conversation_id=None, document=None, create=True):
    """Return the requested conversation, or a new one if the id is missing/unknown
    (None instead when create=False)."""
    if conversation_id:
        try:
            conv = Conversation.objects.filter(id=uuid.UUID(str(conversation_id))).first()
        except ValueError:
            conv = None
        if conv and (document is None or conv.document_id == document.id):
            return conv
    return Conversation.objects.create(document=document) if create else None


def _recent(conv, limit, exclude_ids=()):
    qs = conv.messages.exclude(id__in=exclude_ids).order_by("-id").prefetch_related("attachments")
    return list(qs[:limit])[::-1]


def last_turn(conv):
    """
    The latest user question + assistant answer, for regeneration:
    {"ids", "message", "images", "image_info", "extra_context"} or None.
    """
    msgs = list(conv.messages.order_by("-id").prefetch_related("attachments")[:2])[::-1]
    if len(msgs) != 2 or msgs[0].role != ChatMessage.ROLE_USER or msgs[1].role != ChatMessage.ROLE_ASSISTANT:
        return None
    user = msgs[0]
    atts = list(user.attachments.all())
    return {
        "ids": [m.id for m in msgs],
        "message": user.content,
        "images": [_attachment_b64(a) for a in atts],
        "image_info": [{"width": a.width, "height": a.height,
                        "format": "JPEG" if a.file.name.lower().endswith(".jpg") else "PNG"} for a in atts],
        "extra_context": user.extra_context,
    }


def discard(message_ids):
    """Delete messages (e.g. the turn being regenerated) and their image files."""
    ChatMessage.objects.filter(id__in=message_ids).delete()


def signals(conv, exclude_ids=()) -> dict:
    """Context signals for the router: is an earlier image available, what was the last route?"""
    recent = _recent(conv, _image_turns(), exclude_ids)
    image_available = any(m.attachments.all() for m in recent if m.role == ChatMessage.ROLE_USER)
    last_assistant = next((m for m in reversed(recent) if m.role == ChatMessage.ROLE_ASSISTANT), None)
    return {
        "image_available": image_available,
        "last_reason": last_assistant.routing_reason if last_assistant else None,
    }


def _attachment_b64(att) -> str:
    att.file.open("rb")
    try:
        return base64.b64encode(att.file.read()).decode()
    finally:
        att.file.close()


EARLIER_NOTE_CHARS = 700


def _earlier_topics(conv, included_ids, exclude_ids=()):
    """
    Short note listing what the user asked in messages that no longer fit the context
    window, so long conversations keep their thread (no model call, no summarisation).
    """
    older = (conv.messages.filter(role=ChatMessage.ROLE_USER).exclude(id__in=included_ids)
             .exclude(id__in=exclude_ids).order_by("-id"))
    lines, used = [], 0
    for m in older[:12]:
        first = " ".join((m.content or "").split())[:90]
        if not first or used + len(first) > EARLIER_NOTE_CHARS - 120:
            break
        lines.append(f"- {first}")
        used += len(first) + 3
    if not lines:
        return ""
    return ("Earlier in this conversation (older messages not included in full), the user asked about:\n"
            + "\n".join(reversed(lines)))


def build_messages(conv, user_text, model_tag, new_images=None, system=None, reserved_chars=0,
                   extra_context="", exclude_ids=()):
    """
    Build Ollama chat messages: [system?] + bounded history + current user message.
    `extra_context` (e.g. OCR text of the attached images) is appended to the current message.
    Returns (messages, info) where info reports what context was used.
    """
    if extra_context:
        user_text = f"{user_text}\n\n{extra_context}"
    model = get_model(model_tag)
    new_images = new_images or []
    cpt = chars_per_token(model)
    budget = int(prompt_budget_tokens(model) * cpt) - len(user_text) - len(system or "") - reserved_chars

    history = _recent(conv, _max_messages(), exclude_ids)
    reuse_images = []
    reused_from = None
    if model.supports_images and not new_images:
        # Re-send only the most recent earlier images (VRAM / context protection).
        for m in reversed(history):
            atts = list(m.attachments.all()) if m.role == ChatMessage.ROLE_USER else []
            if atts:
                reuse_images, reused_from = atts, m.id
                break
    image_count = len(new_images) + len(reuse_images)
    budget -= int(image_count * TOKENS_PER_IMAGE * cpt)

    # If the whole history cannot fit, keep room for a short list of earlier topics (L3).
    older_count = conv.messages.exclude(id__in=exclude_ids).count() - len(history)
    total_chars = sum(len(m.content) + len(m.extra_context or "") for m in history)
    if older_count > 0 or total_chars > budget:
        budget -= EARLIER_NOTE_CHARS

    selected = []
    used = 0
    for m in reversed(history):  # newest first, stop when the budget is spent
        content = f"{m.content}\n\n{m.extra_context}" if m.extra_context else m.content
        n_atts = len(m.attachments.all())
        if n_atts and not (m.id == reused_from):
            content = f"[user attached {n_atts} image(s)]\n{content}"
        if used + len(content) > budget:
            break
        used += len(content)
        selected.append((m, content))
    selected.reverse()
    if reused_from and reused_from not in {m.id for m, _ in selected}:
        reuse_images, reused_from = [], None  # the image turn itself no longer fits

    messages = [{"role": "system", "content": system}] if system else []
    note = _earlier_topics(conv, {m.id for m, _ in selected}, exclude_ids)
    if note:
        messages.append({"role": "system", "content": note})
    for m, content in selected:
        entry = {"role": m.role, "content": content}
        if m.id == reused_from:
            entry["images"] = [_attachment_b64(a) for a in reuse_images]
        messages.append(entry)
    current = {"role": "user", "content": user_text}
    if new_images:
        current["images"] = new_images
    messages.append(current)

    available = conv.messages.exclude(id__in=exclude_ids).count()
    info = {
        "earlier_topics_note": bool(note),
        "history_messages_used": len(selected),
        "history_messages_available": available,
        "history_truncated": len(selected) < available,
        "reused_images": len(reuse_images),
    }
    logger.info(
        "Context built: conversation=%s model=%s history=%d/%d reused_images=%d new_images=%d",
        conv.id, model.id, info["history_messages_used"], info["history_messages_available"],
        info["reused_images"], len(new_images),
    )
    return messages, info


def record_turn(conv, user_text, assistant_text, model_tag="", reason="", images=None, image_info=None,
                extra_context="", basis=None):
    """Persist one user/assistant exchange (and the user's prepared images)."""
    user_msg = ChatMessage.objects.create(
        conversation=conv, role=ChatMessage.ROLE_USER, content=user_text, extra_context=extra_context or "",
    )
    for idx, b64 in enumerate(images or []):
        meta = image_info[idx] if image_info and idx < len(image_info) else {}
        ext = "jpg" if meta.get("format") == "JPEG" else "png"
        att = ChatAttachment(message=user_msg, width=meta.get("width", 0), height=meta.get("height", 0))
        att.file.save(f"{uuid.uuid4().hex}.{ext}", ContentFile(base64.b64decode(b64)), save=True)
    ChatMessage.objects.create(
        conversation=conv, role=ChatMessage.ROLE_ASSISTANT, content=assistant_text,
        model=model_tag or "", routing_reason=reason or "",
        basis=(basis or {}).get("type", ""), basis_detail=(basis or {}).get("detail", ""),
        basis_undetermined=bool((basis or {}).get("undetermined")),
        basis_warnings=(basis or {}).get("warnings") or [],
    )
    if not conv.title:
        conv.title = user_text.strip().splitlines()[0][:80] if user_text.strip() else "Conversation"
    conv.save()  # bumps updated_at


def _basis_out(m):
    if m.role != ChatMessage.ROLE_ASSISTANT or not m.basis:
        return None
    from .reliability import LABELS, UNDETERMINED_LABELS
    label = UNDETERMINED_LABELS.get(m.basis) if m.basis_undetermined else LABELS.get(m.basis)
    return {"type": m.basis, "label": label or "", "detail": m.basis_detail, "undetermined": m.basis_undetermined,
            "warnings": m.basis_warnings or []}


def serialize(conv) -> dict:
    return {
        "id": str(conv.id),
        "title": conv.title,
        "document_id": conv.document_id,
        "updated_at": conv.updated_at,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "model": m.model or None,
                "routing_reason": m.routing_reason or None,
                "basis": _basis_out(m),
                "images": [a.file.url for a in m.attachments.all()],
                "created_at": m.created_at,
            }
            for m in conv.messages.prefetch_related("attachments")
        ],
    }
