from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

from chat.views import ModelListAPIView, ModelWarmupAPIView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/chat/", include("chat.urls")),
    path("api/models/", ModelListAPIView.as_view(), name="models"),
    path("api/models/warmup/", ModelWarmupAPIView.as_view(), name="models-warmup"),
    path("api/documents/", include("documents.urls")),
    path("api/dashboard/", include("monitoring.urls")),
    path("api/knowledge/", include("knowledge.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
