import os
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from .models import Document
from .serializers import (
    DocumentListSerializer,
    DocumentDetailSerializer,
    DocumentUploadSerializer,
    DocumentAskSerializer,
    DocumentReportSerializer,
)
from .extractors import (
    validate_file_extension,
    extract_document,
    DocumentExtractionError,
)
from chat.model_manager import ModelManager, ModelManagerError
from chat.views import ndjson_stream, streaming_response, StreamNegotiation
from .services import (
    NothingToRegenerate,
    prepare_document_question,
    finish_document_question,
    ask_document_question,
    summarize_document,
    OllamaServiceError,
)
from .generators import generate_document_docx_report
from .ocr import allowed_languages, default_language, LANGUAGE_NAMES

class DocumentUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = DocumentUploadSerializer(data=request.data)
        if not serializer.is_valid():
            messages = []
            for field, errs in serializer.errors.items():
                err_text = ", ".join([str(e) for e in errs]) if isinstance(errs, list) else str(errs)
                messages.append(f"{err_text}")
            error_msg = "; ".join(messages)
            return Response(
                {"success": False, "error": error_msg, "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_file = serializer.validated_data["file"]

        # Validate extension & detect type
        try:
            file_type = validate_file_extension(uploaded_file.name)
        except DocumentExtractionError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Extract text: PyMuPDF text layer, TXT reader, or local PaddleOCR for scans/images
        try:
            ocr_lang = serializer.validated_data.get("ocr_lang") or default_language()
            extraction = extract_document(uploaded_file, file_type, lang=ocr_lang)
        except DocumentExtractionError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            return Response(
                {"success": False, "error": f"Failed to process document: {str(exc)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Reset pointer for saving file to storage
        uploaded_file.seek(0)

        # Save to database
        doc = Document.objects.create(
            file=uploaded_file,
            original_name=uploaded_file.name,
            file_type=file_type,
            extracted_text=extraction["text"],
            extraction_method=extraction["method"],
            ocr_pages=extraction["ocr_pages"],
            ocr_confidence=extraction["ocr_confidence"],
            page_count=extraction["page_count"],
            ocr_pages_skipped=extraction["ocr_pages_skipped"],
            truncated=extraction["truncated"],
            original_chars=extraction["original_chars"],
            ocr_lang=ocr_lang if extraction["ocr_pages"] else "",
            complex_layout=extraction["complex_layout"],
        )

        return Response(
            {
                "success": True,
                "message": (
                    "Document uploaded and text extracted with local OCR."
                    if extraction["ocr_pages"] else "Document uploaded and extracted successfully."
                ),
                "document": DocumentDetailSerializer(doc).data,
            },
            status=status.HTTP_201_CREATED,
        )

class DocumentListView(APIView):
    def get(self, request):
        documents = Document.objects.all()
        serializer = DocumentListSerializer(documents, many=True)
        return Response({"success": True, "documents": serializer.data})

class DocumentDetailView(APIView):
    def get(self, request, pk):
        doc = get_object_or_404(Document, pk=pk)
        serializer = DocumentDetailSerializer(doc)
        return Response({"success": True, "document": serializer.data})

    def delete(self, request, pk):
        doc = get_object_or_404(Document, pk=pk)
        original_name = doc.original_name
        doc.delete()
        return Response(
            {"success": True, "message": f"Document '{original_name}' deleted successfully."},
            status=status.HTTP_200_OK,
        )

class DocumentAskView(APIView):
    def post(self, request, pk):
        doc = get_object_or_404(Document, pk=pk)
        serializer = DocumentAskSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        v = serializer.validated_data
        try:
            result = ask_document_question(
                doc, v.get("question"), conversation_id=v.get("conversation_id"), regenerate=v["regenerate"],
            )
            return Response({"success": True, **result, "external_api": False})
        except NothingToRegenerate:
            return Response({"success": False, "error": "There is no answer to regenerate."},
                            status=status.HTTP_400_BAD_REQUEST)
        except OllamaServiceError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class DocumentAskStreamView(APIView):
    """Streaming variant of DocumentAskView (NDJSON, same event format as /api/chat/stream/)."""

    content_negotiation_class = StreamNegotiation

    def post(self, request, pk):
        doc = get_object_or_404(Document, pk=pk)
        serializer = DocumentAskSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        v = serializer.validated_data
        try:
            prepared = prepare_document_question(doc, v.get("question"), v.get("conversation_id"), v["regenerate"])
        except NothingToRegenerate:
            return Response({"success": False, "error": "There is no answer to regenerate."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            opened = ModelManager().chat_stream(prepared["decision"]["model"], prepared["messages"])
        except ModelManagerError as exc:
            return Response({"success": False, "error": exc.public_message},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return streaming_response(ndjson_stream(
            opened, prepared["meta"], lambda event: finish_document_question(prepared, event),
        ))

class DocumentSummaryView(APIView):
    def post(self, request, pk):
        doc = get_object_or_404(Document, pk=pk)

        try:
            result = summarize_document(doc)
            return Response({"success": True, **result, "external_api": False})
        except OllamaServiceError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

class DocumentGenerateReportView(APIView):
    def post(self, request, pk):
        doc = get_object_or_404(Document, pk=pk)
        serializer = DocumentReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        summary_text = serializer.validated_data.get("summary", "")

        docx_buffer = generate_document_docx_report(doc, summary_text)

        base_name, _ = os.path.splitext(doc.original_name)
        download_filename = f"{base_name}_MRPL_Report.docx"

        response = HttpResponse(
            docx_buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        response["Content-Disposition"] = f'attachment; filename="{download_filename}"'
        response["Access-Control-Expose-Headers"] = "Content-Disposition"
        return response


class OCRConfigView(APIView):
    """OCR languages users may choose (settings.OCR_ALLOWED_LANGS) and the default."""

    def get(self, request):
        return Response({
            "languages": [{"code": c, "name": LANGUAGE_NAMES[c]} for c in allowed_languages()],
            "default": default_language(),
        })
