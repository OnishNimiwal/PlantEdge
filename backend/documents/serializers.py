from rest_framework import serializers
from .models import Document
from .extractors import validate_file_extension, DocumentExtractionError

class DocumentListSerializer(serializers.ModelSerializer):
    text_length = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = ['id', 'original_name', 'file_type', 'extraction_method', 'uploaded_at', 'text_length',
                  'status', 'progress_done', 'progress_total']

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
            'ocr_lang',
            'complex_layout',
            'vision_fallback_pages',
            'status',
            'progress_done',
            'progress_total',
            'processing_error',
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
    # OCR language for scanned pages / images (must be in settings.OCR_ALLOWED_LANGS)
    ocr_lang = serializers.CharField(required=False, allow_blank=True)

    def validate_ocr_lang(self, value):
        from .ocr import allowed_languages, default_language
        if not value:
            return default_language()
        if value not in allowed_languages():
            raise serializers.ValidationError(
                f"OCR language '{value}' is not enabled. Allowed: {', '.join(allowed_languages())}."
            )
        return value

    def validate_file(self, value):
        if value.size == 0:
            raise serializers.ValidationError("The uploaded file is empty.")
        try:
            validate_file_extension(value.name)
        except DocumentExtractionError as exc:
            raise serializers.ValidationError(str(exc))
        return value

class DocumentAskSerializer(serializers.Serializer):
    question = serializers.CharField(required=False, allow_blank=False, max_length=2000)
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
    regenerate = serializers.BooleanField(required=False, default=False)
    think = serializers.BooleanField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        if attrs.get("regenerate"):
            if not attrs.get("conversation_id"):
                raise serializers.ValidationError({"conversation_id": ["Required to regenerate."]})
        elif not attrs.get("question"):
            raise serializers.ValidationError({"question": ["This field is required."]})
        return attrs

class DocumentReportSerializer(serializers.Serializer):
    summary = serializers.CharField(required=False, allow_blank=True, default="")
