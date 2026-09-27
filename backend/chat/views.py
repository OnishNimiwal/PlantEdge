import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .serializers import ChatSerializer
from .model_registry import list_models, get_default_model_id, UnknownModelError
from .model_manager import (
    ModelManager,
    ModelManagerError,
    ModelTimeoutError,
    ModelUnavailableError,
    ModelNotInstalledError,
)

logger = logging.getLogger(__name__)

ERROR_STATUS = {
    ModelUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ModelNotInstalledError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ModelTimeoutError: status.HTTP_504_GATEWAY_TIMEOUT,
}


class ChatAPIView(APIView):
    def post(self, request):
        serializer = ChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        model_id = data["model"]
        try:
            result = ModelManager().generate(
                model_id, data["message"], images=data.get("images")
            )
        except UnknownModelError:
            return Response({
                "success": False,
                "error": f"Unknown model '{model_id}'.",
                "model": model_id,
            }, status=status.HTTP_400_BAD_REQUEST)
        except ModelManagerError as exc:
            return Response({
                "success": False,
                "error": exc.public_message,
                "model": model_id,
            }, status=ERROR_STATUS.get(type(exc), status.HTTP_502_BAD_GATEWAY))
        except Exception:
            logger.exception("Unexpected error during chat inference: model=%s", model_id)
            return Response({
                "success": False,
                "error": "Local AI server is unavailable.",
                "model": model_id,
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response({
            "success": True,
            "response": result["response"],
            "model": result["model"],
            "ollama_model": result["ollama_model"],
            "duration_ms": result["duration_ms"],
            "external_api": False,
        })


class ModelListAPIView(APIView):
    def get(self, request):
        return Response({
            "models": [m.to_dict() for m in list_models()],
            "default": get_default_model_id(),
        })
