import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .serializers import ChatSerializer, AUTO_MODEL
from .model_registry import list_models, get_default_model_id, get_model, UnknownModelError
from .model_manager import (
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


class ChatAPIView(APIView):
    def post(self, request):
        serializer = ChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        image_info = getattr(serializer, "image_info", [])

        # 0. Context: backend-held conversation (history + earlier images).
        replaced_ids, reused_ocr = (), ""
        if data.get("regenerate"):
            # Re-run the last question (same images / OCR text). The old answer is
            # only removed once the new one succeeds.
            conv = ctx.load(data["conversation_id"], create=False)
            turn = ctx.last_turn(conv) if conv else None
            if not turn:
                return Response({"success": False, "error": "There is no answer to regenerate."},
                                status=status.HTTP_400_BAD_REQUEST)
            replaced_ids, reused_ocr = turn["ids"], turn["extra_context"]
            data["message"], data["images"], image_info = turn["message"], turn["images"] or None, turn["image_info"]
        else:
            conv = ctx.load(data.get("conversation_id"))
        signals = ctx.signals(conv, exclude_ids=replaced_ids)

        # 1. Selection: router decides WHICH model (context-aware).
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
            })

        # 1b. Document processing: local OCR when the router asks for it (image of a document).
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
                return Response({
                    "success": False, "error": f"Local OCR failed: {exc}",
                    "model": model_id, "routing": routing,
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            extra_context, ocr_info = ocr_out["text"], ocr_out["results"]
            if selection["reason"] == REASON_OCR_TEXT:
                images_for_model = None  # the text model reasons over the OCR text only

        try:
            messages, context_info = ctx.build_messages(
                conv, data["message"], selection["model"], new_images=images_for_model,
                extra_context=extra_context, exclude_ids=replaced_ids,
            )
            # 2. Execution: the execution layer decides HOW to call it (local Ollama only).
            result = generate_response(selection["model"], messages=messages)
        except UnknownModelError:
            return Response({
                "success": False,
                "error": f"Unknown model '{model_id}'.",
                "model": model_id,
                "routing": routing,
            }, status=status.HTTP_400_BAD_REQUEST)
        except ModelManagerError as exc:
            return Response({
                "success": False,
                "error": exc.public_message,
                "model": model_id,
                "routing": routing,
            }, status=ERROR_STATUS.get(type(exc), status.HTTP_502_BAD_GATEWAY))
        except Exception:
            logger.exception("Unexpected error during chat inference: model=%s", model_id)
            return Response({
                "success": False,
                "error": "Local AI server is unavailable.",
                "model": model_id,
                "routing": routing,
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        ctx.discard(replaced_ids)
        ctx.record_turn(
            conv, data["message"], result["response"], model_tag=result["ollama_model"],
            reason=selection["reason"], images=data.get("images"), image_info=image_info,
            extra_context=extra_context,
        )
        return Response({
            "success": True,
            "conversation_id": str(conv.id),
            "response": result["response"],
            "model": result["model"],
            "ollama_model": result["ollama_model"],
            "routing": routing,
            "context": context_info,
            "ocr": ocr_info,
            "duration_ms": result["duration_ms"],
            "images": image_info,
            "context_overflow": result["context_overflow"],
            "external_api": False,
        })


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
    """Recent conversations, optionally for one document (?document=<id>)."""

    def get(self, request):
        qs = Conversation.objects.all()
        doc = request.query_params.get("document")
        qs = qs.filter(document_id=doc) if doc else qs.filter(document__isnull=True)
        return Response({"conversations": [
            {"id": str(c.id), "title": c.title, "updated_at": c.updated_at}
            for c in qs[:50]
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
