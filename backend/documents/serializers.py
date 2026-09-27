from rest_framework import serializers
from .models import Document
from .extractors import validate_file_extension, DocumentExtractionError

class DocumentListSerializer(serializers.ModelSerializer):
    text_length = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = ['id', 'original_name', 'file_type', 'extraction_method', 'uploaded_at', 'text_length']

    def get_text_length(self, obj):
        return len(obj.extracted_text) if obj.extracted_text else 0

class DocumentDetailSerializer(serializers.ModelSerializer):
    text_length = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    limits = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            'id',
            'original_name',
            'file_type',
            'extracted_text',
            'extraction_method',
            'ocr_pages',
            'ocr_confidence',
            'page_count',
            'ocr_pages_skipped',
            'truncated',
            'original_chars',
            'limits',
            'uploaded_at',
            'text_length',
            'file_url',
        ]

    def get_text_length(self, obj):
        return len(obj.extracted_text) if obj.extracted_text else 0

    def get_limits(self, obj):
        from django.conf import settings
        return {
            "max_chars": settings.DOCUMENT_MAX_CHARS,
            "max_ocr_pages": settings.OCR_MAX_PDF_PAGES,
            "max_pdf_pages": settings.DOCUMENT_MAX_PDF_PAGES,
        }

    def get_file_url(self, obj):
        if obj.file:
            return obj.file.url
        return None

class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField(required=True)

    def validate_file(self, value):
        if value.size == 0:
            raise serializers.ValidationError("The uploaded file is empty.")
        try:
            validate_file_extension(value.name)
        except DocumentExtractionError as exc:
            raise serializers.ValidationError(str(exc))
        return value

class DocumentAskSerializer(serializers.Serializer):
    question = serializers.CharField(required=True, allow_blank=False, max_length=2000)
    conversation_id = serializers.UUIDField(required=False, allow_null=True)

class DocumentReportSerializer(serializers.Serializer):
    summary = serializers.CharField(required=False, allow_blank=True, default="")
