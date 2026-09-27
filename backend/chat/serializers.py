import base64
import binascii

from rest_framework import serializers

from .model_registry import MODEL_REGISTRY

# Special model value: let chat/router.py pick the model.
AUTO_MODEL = "auto"

# Image formats accepted by the local vision model, identified by magic bytes.
IMAGE_SIGNATURES = (
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"\xff\xd8\xff",       # JPEG
)
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class ChatSerializer(serializers.Serializer):
    message = serializers.CharField(required=True, allow_blank=False)
    # "auto" (default when omitted) -> router picks; a registry id -> manual choice.
    model = serializers.CharField(required=False, allow_blank=False, default=AUTO_MODEL)
    # Base64-encoded images (a data: URL prefix is tolerated). Vision models / auto only.
    images = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        max_length=1,
    )

    def validate_model(self, value):
        if value != AUTO_MODEL and value not in MODEL_REGISTRY:
            raise serializers.ValidationError(
                f"Unknown model '{value}'. Available models: "
                f"{', '.join([AUTO_MODEL, *MODEL_REGISTRY])}."
            )
        return value

    def validate_images(self, value):
        cleaned = []
        for item in value:
            if item.startswith("data:") and "," in item:
                item = item.split(",", 1)[1]
            try:
                raw = base64.b64decode(item, validate=True)
            except (binascii.Error, ValueError):
                raise serializers.ValidationError("Image must be valid base64 data.")
            if len(raw) > MAX_IMAGE_BYTES:
                raise serializers.ValidationError("Image exceeds the 10 MB limit.")
            if not raw.startswith(IMAGE_SIGNATURES):
                raise serializers.ValidationError("Only PNG and JPEG images are supported.")
            cleaned.append(item)
        return cleaned

    def validate(self, attrs):
        model = attrs["model"]
        if attrs.get("images") and model != AUTO_MODEL and not MODEL_REGISTRY[model].supports_images:
            raise serializers.ValidationError(
                {"images": f"Model '{attrs['model']}' does not accept images. Select a vision model."}
            )
        return attrs
