from rest_framework.response import Response
from rest_framework.views import APIView

from . import health, usage


class UsageDashboardView(APIView):
    """GET /api/dashboard/usage/?tz_offset=<minutes> - aggregated model usage (no content)."""

    def get(self, request):
        try:
            offset = int(request.query_params.get("tz_offset", 0))
        except ValueError:
            offset = 0
        offset = max(-14 * 60, min(14 * 60, offset))
        return Response(usage.summary(offset))


class SystemStatusView(APIView):
    """GET /api/dashboard/status/ - backend / Ollama / OCR status and model health (no inference)."""

    def get(self, request):
        return Response(health.full_status())


class DeepCheckView(APIView):
    """
    POST /api/dashboard/deep-check/ {"target": "ocr" | "<model id>"} - opt-in functional test
    (runs OCR on a generated image, or a tiny generation). Only on explicit user request.
    """

    def post(self, request):
        target = request.data.get("target")
        if not isinstance(target, str):
            return Response({"success": False, "error": "target is required."}, status=400)
        try:
            return Response(health.deep_check(target))
        except ValueError as exc:
            return Response({"success": False, "error": str(exc)}, status=400)
