from django.urls import path
from .views import (
    DocumentUploadView,
    DocumentListView,
    DocumentDetailView,
    DocumentAskView,
    DocumentAskStreamView,
    DocumentSummaryView,
    DocumentGenerateReportView,
    OCRConfigView,
)

urlpatterns = [
    path("", DocumentListView.as_view(), name="document-list"),
    path("upload/", DocumentUploadView.as_view(), name="document-upload"),
    path("ocr-config/", OCRConfigView.as_view(), name="document-ocr-config"),
    path("<int:pk>/", DocumentDetailView.as_view(), name="document-detail"),
    path("<int:pk>/ask/", DocumentAskView.as_view(), name="document-ask"),
    path("<int:pk>/ask/stream/", DocumentAskStreamView.as_view(), name="document-ask-stream"),
    path("<int:pk>/summary/", DocumentSummaryView.as_view(), name="document-summary"),
    path("<int:pk>/generate-report/", DocumentGenerateReportView.as_view(), name="document-generate-report"),
]
