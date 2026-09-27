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
            'uploaded_at',
            'text_length',
            'file_url',
        ]

    def get_text_length(self, obj):
        return len(obj.extracted_text) if obj.extracted_text else 0

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

class DocumentReportSerializer(serializers.Serializer):
    summary = serializers.CharField(required=False, allow_blank=True, default="")
