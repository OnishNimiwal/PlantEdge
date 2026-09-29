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
