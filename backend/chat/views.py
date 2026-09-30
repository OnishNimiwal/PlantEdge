import json
import logging

from django.conf import settings
from django.db.models import Q
from django.http import StreamingHttpResponse
from rest_framework.negotiation import BaseContentNegotiation
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .serializers import ChatSerializer, AUTO_MODEL
from .model_registry import list_models, get_default_model_id, get_model, UnknownModelError
from .model_manager import (
    ModelManager,
    loaded_models,
    warm_up,
    generate_response,
    ModelManagerError,
    ModelTimeoutError,
    ModelUnavailableError,
    ModelNotInstalledError,
    NonLocalEndpointError,
    ModelResourceError,
)
from .router import route_model, REASON_OCR_TEXT
from . import context as ctx
from . import reliability
from documents import processing
from .models import Conversation

logger = logging.getLogger(__name__)

ERROR_STATUS = {
    ModelUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ModelNotInstalledError: status.HTTP_503_SERVICE_UNAVAILABLE,
    NonLocalEndpointError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ModelResourceError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ModelTimeoutError: status.HTTP_504_GATEWAY_TIMEOUT,
}

NEEDS_IMAGE_MESSAGE = (
    "This looks like a request about an image, but no image is attached. "
    "Please attach a PNG or JPEG image and ask again."
)


def select_model(data, signals=None) -> dict:
    """
    Selection step: router for "auto", otherwise the user's manual choice.
    `signals` are context signals from chat/context.py (earlier image, last route).
    Returns {"model": <ollama tag>, "model_id", "mode", "reason", ...}. No Ollama calls here.
    """
    if data["model"] == AUTO_MODEL:
        decision = route_model(data["message"], has_images=bool(data.get("images")), context=signals)
        return {**decision, "mode": "auto"}
    model = get_model(data["model"])
    return {"model": model.ollama_name, "model_id": model.id, "mode": "manual", "reason": "manual",
            "requires_image": False, "explanation": "model selected manually"}


def _error(message, http_status, model_id=None, routing=None):
    body = {"success": False, "error": message}
    if model_id is not None:
        body["model"] = model_id
    if routing is not None:
        body["routing"] = routing
    return Response(body, status=http_status)


def prepare_turn(data, image_info):
    """
    Everything before model execution, shared by the JSON and streaming endpoints:
    context -> routing -> (OCR) -> bounded message history.
    Returns (early_response, turn): early_response is a Response to return as-is
    (error, or the "attach an image" reply); otherwise turn holds what execution needs.
    """
    data = dict(data)
    replaced_ids, reused_ocr = (), ""
    if data.get("regenerate"):
        # Re-run the last question (same images / OCR text). The old answer is
        # only removed once the new one succeeds.
        conv = ctx.load(data["conversation_id"], create=False)
        last = ctx.last_turn(conv) if conv else None
        if not last:
            return _error("There is no answer to regenerate.", status.HTTP_400_BAD_REQUEST), None
        replaced_ids, reused_ocr = last["ids"], last["extra_context"]
        data["message"], data["images"], image_info = last["message"], last["images"] or None, last["image_info"]
    else:
        conv = ctx.load(data.get("conversation_id"))
    signals = ctx.signals(conv, exclude_ids=replaced_ids)

    # Selection: router decides WHICH model (context-aware).
    selection = select_model(data, signals)
    model_id = selection["model_id"]
    routing = {"mode": selection["mode"], "reason": selection["reason"],
               "explanation": selection["explanation"]}

    # A visual question with nothing to look at: ask for the image instead of
    # sending the request to the vision model, which could only guess.
    if selection["requires_image"]:
        logger.info("Vision request without image: no model called")
        ctx.discard(replaced_ids)
        ctx.record_turn(conv, data["message"], NEEDS_IMAGE_MESSAGE, reason=selection["reason"])
        return Response({
            "success": True,
            "conversation_id": str(conv.id),
            "needs_image": True,
            "response": NEEDS_IMAGE_MESSAGE,
            "model": None,
            "ollama_model": None,
            "routing": routing,
            "external_api": False,
        }), None

    # Document processing: local OCR when the router asks for it (image of a document).
    ocr_info, extra_context = None, ""
    images_for_model = data.get("images")
    if selection.get("ocr") and data.get("images") and reused_ocr:
        extra_context = reused_ocr  # regenerate: reuse the stored OCR text
        if selection["reason"] == REASON_OCR_TEXT:
            images_for_model = None
    elif selection.get("ocr") and data.get("images"):
        try:
            ocr_out = processing.ocr_images(data["images"])
        except processing.OCRError as exc:
            return _error(f"Local OCR failed: {exc}", status.HTTP_503_SERVICE_UNAVAILABLE, model_id, routing), None
        extra_context, ocr_info = ocr_out["text"], ocr_out["results"]
        if selection["reason"] == REASON_OCR_TEXT:
            images_for_model = None  # the text model reasons over the OCR text only

    # Reliability instructions for this kind of request + formatting guidance.
    model_obj = get_model(selection["model"])
    mode = reliability.mode_for(
        selection["reason"], model_obj, bool(images_for_model) or signals.get("image_available", False),
    )
    system = reliability.system_prompt(mode, getattr(settings, "CHAT_SYSTEM_PROMPT", "")) or None
    messages, context_info = ctx.build_messages(
        conv, data["message"], selection["model"], new_images=images_for_model,
        extra_context=extra_context, exclude_ids=replaced_ids, system=system,
    )
    return None, {
        "conv": conv, "data": data, "selection": selection, "model_id": model_id,
        "routing": routing, "messages": messages, "context_info": context_info,
        "extra_context": extra_context, "ocr_info": ocr_info, "image_info": image_info,
        "replaced_ids": replaced_ids,
        "basis_kind": reliability.chat_basis_kind(
            selection["reason"], any(m.get("images") for m in messages), bool(extra_context), model_obj,
        ),
        "usage": {"reason": selection["reason"], "source": "chat"},
        "think": data.get("think"),
    }


def _thinking_enabled(turn):
    model = get_model(turn["selection"]["model"])
    think = turn["think"] if turn["think"] is not None else getattr(settings, "OLLAMA_THINK", None)
    return bool(model.supports_thinking and think)


def finish_turn(turn, result):
    """Persist the exchange (replacing a regenerated turn) and build the response body."""
    detail = "with OCR text" if turn["basis_kind"] == "image" and turn["extra_context"] else ""
    basis = reliability.basis(turn["basis_kind"], result["response"], detail)
    basis["warnings"] = []
    if turn["basis_kind"] == "image_text" and not basis["undetermined"]:
        from documents.verify import check_numbers
        missing = check_numbers(result["response"], turn["extra_context"], turn["data"]["message"])
        if missing:
            basis["warnings"].append(f"Value{'s' if len(missing) > 1 else ''} not found in the OCR text: "
                                     f"{', '.join(missing)}")
    if turn["basis_kind"] == "code" and reliability.execution_claims(result["response"]):
        basis["warnings"].append("The answer says the code was run or tested, but the workbench did not execute it.")
    ctx.discard(turn["replaced_ids"])
    ctx.record_turn(
        turn["conv"], turn["data"]["message"], result["response"], model_tag=result["ollama_model"],
        reason=turn["selection"]["reason"], images=turn["data"].get("images"),
        image_info=turn["image_info"], extra_context=turn["extra_context"], basis=basis,
    )
    return {
        "success": True,
        "conversation_id": str(turn["conv"].id),
        "response": result["response"],
        "model": result["model"],
        "ollama_model": result["ollama_model"],
        "routing": turn["routing"],
        "context": turn["context_info"],
        "basis": basis,
        "ocr": turn["ocr_info"],
        "duration_ms": result["duration_ms"],
        "images": turn["image_info"],
        "context_overflow": result.get("context_overflow", False),
        "external_api": False,
    }


def _model_error(exc, turn):
    if isinstance(exc, UnknownModelError):
        return _error(f"Unknown model '{turn['model_id']}'.", status.HTTP_400_BAD_REQUEST,
                      turn["model_id"], turn["routing"])
    if isinstance(exc, ModelManagerError):
        return _error(exc.public_message, ERROR_STATUS.get(type(exc), status.HTTP_502_BAD_GATEWAY),
                      turn["model_id"], turn["routing"])
    logger.exception("Unexpected error during chat inference: model=%s", turn["model_id"])
    return _error("Local AI server is unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE,
                  turn["model_id"], turn["routing"])


class ChatAPIView(APIView):
    def post(self, request):
        serializer = ChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        early, turn = prepare_turn(serializer.validated_data, getattr(serializer, "image_info", []))
        if early is not None:
            return early
        try:
            # Execution: the execution layer decides HOW to call it (local Ollama only).
            result = generate_response(turn["selection"]["model"], messages=turn["messages"], usage=turn["usage"],
                                       think=turn["think"])
        except Exception as exc:
            return _model_error(exc, turn)
        return Response(finish_turn(turn, result))


def ndjson_stream(opened, meta, on_done):
    """
    Serialise stream events as NDJSON lines. `opened` is a ChatStream; `on_done(event)`
    persists the turn and returns extra fields for the final "done" line.
    """
    yield json.dumps({"type": "start", **meta}) + "\n"
    try:
        for event in opened:
            if event["type"] == "done":
                yield json.dumps({"type": "done", **on_done(event)}, default=str) + "\n"
                return
            yield json.dumps(event) + "\n"
    except ModelManagerError as exc:
        yield json.dumps({"type": "error", "error": exc.public_message}) + "\n"
    except Exception:
        logger.exception("Unexpected error while streaming")
        yield json.dumps({"type": "error", "error": "Local AI server is unavailable."}) + "\n"


class StreamNegotiation(BaseContentNegotiation):
    """
    Streaming endpoints answer with NDJSON (a plain Django StreamingHttpResponse) or,
    for errors before streaming starts, JSON. Never reject a request with 406 just
    because the client asked for application/x-ndjson.
    """

    def select_parser(self, request, parsers):
        return parsers[0]

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type


def streaming_response(generator):
    response = StreamingHttpResponse(generator, content_type="application/x-ndjson")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # disable proxy buffering (e.g. nginx)
    return response


class ChatStreamAPIView(APIView):
    content_negotiation_class = StreamNegotiation
    """
    Same request as ChatAPIView, answered as a stream of NDJSON lines:
      {"type":"start", conversation_id, routing, ocr, images}
      {"type":"thinking"}                        (optional, once)
      {"type":"delta", "text"}                   (many)
      {"type":"done", ...same fields as the JSON endpoint}  or  {"type":"error", "error"}
    Errors before generation starts (validation, Ollama unavailable, GPU OOM...) are
    returned as normal JSON error responses; the "attach an image" reply is plain JSON too.
    """

    def post(self, request):
        serializer = ChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        early, turn = prepare_turn(serializer.validated_data, getattr(serializer, "image_info", []))
        if early is not None:
            return early
        # Tell the UI when the model still has to be loaded into GPU memory (~12-16 s).
        model_loading = turn["selection"]["model"] not in loaded_models()
        try:
            opened = ModelManager().chat_stream(turn["selection"]["model"], turn["messages"], usage=turn["usage"],
                                                think=turn["think"])
        except Exception as exc:
            return _model_error(exc, turn)
        meta = {"conversation_id": str(turn["conv"].id), "routing": turn["routing"],
                "ollama_model": turn["selection"]["model"], "ocr": turn["ocr_info"], "images": turn["image_info"],
                "model_loading": model_loading, "thinking_enabled": _thinking_enabled(turn)}
        # The turn is stored only when the stream completes (a dropped connection stores nothing).
        return streaming_response(ndjson_stream(opened, meta, lambda event: finish_turn(turn, event)))


class RouteAPIView(APIView):
    """Routing decision only (no inference) - for testing/inspecting the router."""

    def post(self, request):
        message = request.data.get("message")
        if not isinstance(message, str) or not message.strip():
            return Response({"message": ["This field is required."]},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(route_model(message, has_images=bool(request.data.get("images"))))


class ModelListAPIView(APIView):
    def get(self, request):
        from django.conf import settings
        return Response({
            "models": [m.to_dict() for m in list_models()],
            "default": get_default_model_id(),
            "limits": {
                "max_images_per_message": settings.MAX_IMAGES_PER_MESSAGE,
                "vision_max_side": settings.VISION_MAX_SIDE,
            },
        })


class ConversationListAPIView(APIView):
    """
    Recent conversations (newest first, up to 50).
      ?document=<id>  only that document's Q&A conversations
      ?scope=all      chat AND document conversations (default: chat only)
      ?q=<text>       search titles and message text (case-insensitive)
    """

    def get(self, request):
        # Conversations whose first message failed have no stored turns; don't list them.
        qs = Conversation.objects.select_related("document").filter(messages__isnull=False).distinct()
        doc = request.query_params.get("document")
        if doc:
            qs = qs.filter(document_id=doc)
        elif request.query_params.get("scope") != "all":
            qs = qs.filter(document__isnull=True)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(messages__content__icontains=q)).distinct()
        return Response({"conversations": [
            {
                "id": str(c.id), "title": c.title, "updated_at": c.updated_at,
                "document_id": c.document_id,
                "document_name": c.document.original_name if c.document_id else None,
            }
            for c in qs.order_by("-updated_at")[:50]
        ]})


class ConversationDetailAPIView(APIView):
    def get(self, request, pk):
        conv = Conversation.objects.filter(pk=pk).first()
        if not conv:
            return Response({"success": False, "error": "Conversation not found."}, status=404)
        return Response({"success": True, "conversation": ctx.serialize(conv)})

    def patch(self, request, pk):
        """Rename: {"title": "..."}."""
        conv = Conversation.objects.filter(pk=pk).first()
        if not conv:
            return Response({"success": False, "error": "Conversation not found."}, status=404)
        title = request.data.get("title")
        if not isinstance(title, str) or not title.strip():
            return Response({"success": False, "error": "Title must not be empty."}, status=400)
        conv.title = title.strip()[:200]
        conv.save(update_fields=["title"])  # renaming does not reorder the list
        return Response({"success": True, "id": str(conv.id), "title": conv.title})

    def delete(self, request, pk):
        deleted, _ = Conversation.objects.filter(pk=pk).delete()
        return Response({"success": bool(deleted)}, status=200 if deleted else 404)


class ModelWarmupAPIView(APIView):
    """
    POST /api/models/warmup/ {"model": "qwen-vl"} - load a model into GPU memory ahead of
    the user's request (no generation). Returns immediately; skipped while busy.
    """

    def post(self, request):
        model_id = request.data.get("model") or get_default_model_id()
        try:
            state = warm_up(model_id)
        except UnknownModelError:
            return Response({"success": False, "error": f"Unknown model '{model_id}'."}, status=400)
        return Response({"success": True, "model": model_id, "state": state})
