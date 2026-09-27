"""
Backend image safety for the vision model (8 GB GPU).

Every image bound for Qwen2.5-VL passes through prepare_image():
  - only PNG / JPEG are accepted
  - images above VISION_MAX_INPUT_PIXELS are rejected before decoding
  - EXIF orientation is applied (phone photos)
  - the longest side is reduced to VISION_MAX_SIDE, preserving aspect ratio
  - images already within limits are passed through byte-for-byte (no re-encoding)

A 1024 px image costs ~1,100 prompt tokens on qwen2.5vl; a 3840x2160 image
exhausted GPU memory before this was enforced.
"""

import base64
import io

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"PNG", "JPEG"}


class ImageValidationError(ValueError):
    """Raised with a client-safe message when an image cannot be used."""


def _limits():
    return (
        int(getattr(settings, "VISION_MAX_SIDE", 1024)),
        int(getattr(settings, "VISION_MAX_INPUT_PIXELS", 50_000_000)),
    )


def prepare_image(raw: bytes) -> dict:
    """
    Validate and, if needed, downscale one image.
    Returns {"b64", "width", "height", "original_width", "original_height", "resized", "format"}.
    """
    max_side, max_pixels = _limits()
    try:
        img = Image.open(io.BytesIO(raw))  # reads the header only
    except (UnidentifiedImageError, OSError):
        raise ImageValidationError("The image could not be decoded. Only PNG and JPEG are supported.")
    if img.format not in ALLOWED_FORMATS:
        raise ImageValidationError("Only PNG and JPEG images are supported.")
    original = img.size
    if original[0] * original[1] > max_pixels:
        raise ImageValidationError(
            f"Image is too large ({original[0]}x{original[1]}). "
            f"The maximum is {max_pixels // 1_000_000} megapixels."
        )

    try:
        transposed = ImageOps.exif_transpose(img)
        needs_resize = max(transposed.size) > max_side
        if transposed is img and not needs_resize:
            return {
                "b64": base64.b64encode(raw).decode(), "width": original[0], "height": original[1],
                "original_width": original[0], "original_height": original[1],
                "resized": False, "format": img.format,
            }
        out = transposed.copy()
        if needs_resize:
            out.thumbnail((max_side, max_side), Image.LANCZOS)  # keeps aspect ratio
        buf = io.BytesIO()
        if img.format == "JPEG":
            out.convert("RGB").save(buf, "JPEG", quality=90)
        else:
            out.save(buf, "PNG")
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ImageValidationError("The image could not be processed.")
    return {
        "b64": base64.b64encode(buf.getvalue()).decode(), "width": out.size[0], "height": out.size[1],
        "original_width": original[0], "original_height": original[1],
        "resized": needs_resize, "format": img.format,
    }
