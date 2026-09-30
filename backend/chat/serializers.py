import base64
import binascii

from django.conf import settings
from rest_framework import serializers

from .images import prepare_image, ImageValidationError
from .model_registry import MODEL_REGISTRY

# Special model value: let chat/router.py pick the model.
AUTO_MODEL = "auto"

MAX_IMAGE_BYTES = 10 * 1024 * 1024


class ChatSerializer(serializers.Serializer):
    # Required unless regenerate=True (then the last question is re-run).
    message = serializers.CharField(required=False, allow_blank=False)
    regenerate = serializers.BooleanField(required=False, default=False)
    # "Think deeper": enable Qwen3 step-by-step reasoning for this message (slower).
    think = serializers.BooleanField(required=False, allow_null=True, default=None)
    # Edit / regenerate an earlier turn: replace this user message and everything after it.
    edit_from = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    # Answer language chosen in the UI ("en" | "hi").
    language = serializers.ChoiceField(choices=["en", "hi"], required=False, default="en")
    # "auto" (default when omitted) -> router picks; a registry id -> manual choice.
    model = serializers.CharField(required=False, allow_blank=False, default=AUTO_MODEL)
    # Conversation to continue (omitted/unknown -> a new conversation is started).
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
    # Base64-encoded images (a data: URL prefix is tolerated). Vision models / auto only.
    images = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
    )

    def validate_model(self, value):
        if value != AUTO_MODEL and value not in MODEL_REGISTRY:
            raise serializers.ValidationError(
                f"Unknown model '{value}'. Available models: "
                f"{', '.join([AUTO_MODEL, *MODEL_REGISTRY])}."
            )
        return value

    def validate_images(self, value):
        """Decode, validate and downscale each image (see chat/images.py)."""
        limit = settings.MAX_IMAGES_PER_MESSAGE
        if len(value) > limit:
            raise serializers.ValidationError(f"At most {limit} images can be attached to one message.")
        cleaned = []
        self.image_info = []
        for item in value:
            if item.startswith("data:") and "," in item:
                item = item.split(",", 1)[1]
            try:
                raw = base64.b64decode(item, validate=True)
            except (binascii.Error, ValueError):
                raise serializers.ValidationError("Image must be valid base64 data.")
            if len(raw) > MAX_IMAGE_BYTES:
                raise serializers.ValidationError("Image exceeds the 10 MB limit.")
            try:
                prepared = prepare_image(raw)
            except ImageValidationError as exc:
                raise serializers.ValidationError(str(exc))
            cleaned.append(prepared.pop("b64"))
            self.image_info.append(prepared)
        return cleaned

    def validate(self, attrs):
        if attrs.get("regenerate") or attrs.get("edit_from"):
            if not attrs.get("conversation_id"):
                raise serializers.ValidationError({"conversation_id": ["Required to regenerate or edit."]})
            if attrs.get("edit_from") and not attrs.get("regenerate") and not attrs.get("message"):
                raise serializers.ValidationError({"message": ["This field is required."]})
        elif not attrs.get("message"):
            raise serializers.ValidationError({"message": ["This field is required."]})
        model = attrs["model"]
        if attrs.get("images") and model != AUTO_MODEL and not MODEL_REGISTRY[model].supports_images:
            raise serializers.ValidationError(
                {"images": f"Model '{attrs['model']}' does not accept images. Select a vision model."}
            )
        return attrs
