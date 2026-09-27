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
)
from .router import route_model

logger = logging.getLogger(__name__)

ERROR_STATUS = {
    ModelUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ModelNotInstalledError: status.HTTP_503_SERVICE_UNAVAILABLE,
    NonLocalEndpointError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ModelTimeoutError: status.HTTP_504_GATEWAY_TIMEOUT,
}


def select_model(data) -> dict:
    """
    Selection step: router for "auto", otherwise the user's manual choice.
    Returns {"model": <ollama tag>, "model_id", "mode", "reason"}. No Ollama calls here.
    """
    if data["model"] == AUTO_MODEL:
        decision = route_model(data["message"], has_images=bool(data.get("images")))
        return {**decision, "mode": "auto"}
    model = get_model(data["model"])
    return {"model": model.ollama_name, "model_id": model.id, "mode": "manual", "reason": "manual"}


class ChatAPIView(APIView):
    def post(self, request):
        serializer = ChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 1. Selection: router decides WHICH model.
        selection = select_model(data)
        model_id = selection["model_id"]
        routing = {"mode": selection["mode"], "reason": selection["reason"]}
        try:
            # 2. Execution: the execution layer decides HOW to call it (local Ollama only).
            result = generate_response(
                selection["model"], data["message"], images=data.get("images")
            )
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

        return Response({
            "success": True,
            "response": result["response"],
            "model": result["model"],
            "ollama_model": result["ollama_model"],
            "routing": routing,
            "duration_ms": result["duration_ms"],
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
        return Response({
            "models": [m.to_dict() for m in list_models()],
            "default": get_default_model_id(),
        })
