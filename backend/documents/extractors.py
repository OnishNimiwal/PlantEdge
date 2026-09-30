import os
import pymupdf  # PyMuPDF fitz
from django.conf import settings

from . import ocr

# Default only; the enforced value is settings.DOCUMENT_MAX_CHARS.
MAX_EXTRACTED_CHARS = 50000
ALLOWED_EXTENSIONS = {
    '.pdf': 'PDF',
    '.txt': 'TXT',
    '.png': 'PNG',
    '.jpg': 'JPG',
    '.jpeg': 'JPG',
}
IMAGE_TYPES = {'PNG', 'JPG'}
IMAGE_SIGNATURES = {
    'PNG': b"\x89PNG\r\n\x1a\n",
    'JPG': b"\xff\xd8\xff",
}
# A PDF page with fewer non-whitespace characters than this is treated as scanned.
MIN_PAGE_TEXT_CHARS = 20

class DocumentExtractionError(Exception):
    """Custom exception raised when document extraction fails."""
    pass

def validate_file_extension(filename: str) -> str:
    """
    Validates that the file has an allowed extension.
    Returns the normalized file_type string ('PDF', 'TXT', 'PNG' or 'JPG').
    """
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise DocumentExtractionError(
            f"Unsupported file type '{ext}'. Only PDF, TXT, PNG and JPG/JPEG files are allowed."
        )
    return ALLOWED_EXTENSIONS[ext]

def _page_has_text(text: str) -> bool:
    return len("".join(text.split())) >= MIN_PAGE_TEXT_CHARS

TRANSCRIBE_PROMPT = (
    "Transcribe all readable text in this image exactly as written, line by line, keeping numbers and units "
    "exactly. Do not summarise, correct, translate or add anything. Write [illegible] for parts you cannot "
    "read. Output only the transcription."
)


def _vision_transcribe(image_b64):
    """
    Second read of a low-confidence page/image by the local vision model (handwriting,
    poor scans). Returns the transcription, or None if unavailable. The result is marked
    as a vision transcription because a vision model can misread or invent text.
    """
    from chat.model_manager import generate_response, ModelManagerError
    try:
        result = generate_response("qwen-vl", TRANSCRIBE_PROMPT, images=[image_b64],
                                   usage={"reason": "vision", "source": "ocr_fallback"})
    except ModelManagerError:
        return None
    text = (result.get("response") or "").strip()
    return text or None


def _needs_vision_fallback(result):
    return (getattr(settings, "OCR_VISION_FALLBACK", True) and result.get("lines", 0) > 0
            and result.get("confidence", 1.0) < getattr(settings, "OCR_VISION_FALLBACK_BELOW", 0.8))


def _page_png_b64(page):
    import base64
    zoom = min(getattr(settings, "VISION_MAX_SIDE", 1024) / max(page.rect.width, page.rect.height), 3.0)
    return base64.b64encode(page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")).decode()


def _join_pages(pages, with_markers):
    """Join page texts; return (text, [[page_number, start_offset], ...]) for page citations."""
    parts, offsets, pos = [], [], 0
    for num, t, via in pages:
        if not with_markers and not t:
            continue
        label = {"ocr": " (OCR)", "vision": " (vision transcription)"}.get(via, "")
        chunk = f"--- Page {num}{label} ---\n{t}" if with_markers else t
        if parts:
            pos += 2  # "\n\n" separator
        offsets.append([num, pos])
        parts.append(chunk)
        pos += len(chunk)
    return "\n\n".join(parts), offsets


def _extract_pdf(file_bytes: bytes, lang: str = None, progress=None) -> dict:
    """Text layer where present; local OCR for scanned (image-only) pages."""
    max_ocr_pages = getattr(settings, "OCR_MAX_PDF_PAGES", 20)
    max_pages = getattr(settings, "DOCUMENT_MAX_PDF_PAGES", 300)
    with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:
        if len(doc) == 0:
            raise DocumentExtractionError("The uploaded PDF has no pages.")
        if len(doc) > max_pages:
            raise DocumentExtractionError(
                f"The PDF has {len(doc)} pages; the maximum is {max_pages}. "
                "Split the document and upload the parts separately."
            )
        page_count = len(doc)

        pages = []  # (page_number, text, via: None | "ocr" | "vision")
        ocr_confidences = []
        complex_layout = False
        vision_pages = 0
        skipped_pages = []
        for page in doc:
            if progress:
                progress(page.number, page_count)
            page_text = page.get_text("text").strip()
            if _page_has_text(page_text):
                pages.append((page.number + 1, page_text, None))
            elif len(ocr_confidences) < max_ocr_pages:
                try:
                    result = ocr.ocr_pdf_page(page, lang)
                except ocr.OCRError as exc:
                    raise DocumentExtractionError(str(exc)) from exc
                ocr_confidences.append(result["confidence"])
                complex_layout = complex_layout or result.get("complex_layout", False)
                via, text_out = "ocr", result["text"]
                if _needs_vision_fallback(result):
                    transcribed = _vision_transcribe(_page_png_b64(page))
                    if transcribed:
                        via, text_out = "vision", transcribed
                        vision_pages += 1
                pages.append((page.number + 1, text_out, via))
            else:
                skipped_pages.append(page.number + 1)

    if progress:
        progress(page_count, page_count)
    ocr_pages = len(ocr_confidences)
    offsets = []
    if not any(t.strip() for _, t, _via in pages):
        text, method = "", ("ocr" if ocr_pages else "text")
    elif ocr_pages == 0:
        # Unchanged text format for normal text PDFs.
        text, offsets = _join_pages(pages, with_markers=False)
        method = "text"
    else:
        text, offsets = _join_pages(pages, with_markers=True)
        method = "ocr" if ocr_pages == len(pages) else "text+ocr"
        if skipped_pages:
            text += (
                f"\n\n[Note: OCR limited to {max_ocr_pages} scanned pages; "
                f"{len(skipped_pages)} further scanned page(s) were not processed]"
            )
    return {
        "text": text.strip(),
        "method": method,
        "ocr_pages": ocr_pages,
        "ocr_confidence": round(sum(ocr_confidences) / ocr_pages, 3) if ocr_pages else None,
        "page_count": page_count,
        "page_offsets": offsets,
        "ocr_pages_skipped": len(skipped_pages),
        "complex_layout": complex_layout,
        "vision_fallback_pages": vision_pages,
    }

def _extract_image(file_bytes: bytes, file_type: str, lang: str = None) -> dict:
    if not file_bytes.startswith(IMAGE_SIGNATURES[file_type]):
        raise DocumentExtractionError(f"The uploaded file is not a valid {file_type} image.")
    try:
        result = ocr.ocr_image(file_bytes, lang)
    except ocr.OCRError as exc:
        raise DocumentExtractionError(str(exc)) from exc
    vision_pages = 0
    if _needs_vision_fallback(result):
        from chat.images import prepare_image, ImageValidationError
        try:
            transcribed = _vision_transcribe(prepare_image(file_bytes)["b64"])
        except ImageValidationError:
            transcribed = None
        if transcribed:
            result = {**result, "text": f"--- Page 1 (vision transcription) ---\n{transcribed}"}
            vision_pages = 1
    return {
        "vision_fallback_pages": vision_pages,
        "text": result["text"].strip(),
        "method": "ocr",
        "ocr_pages": 1,
        "ocr_confidence": result["confidence"],
        "page_count": 1,
        "ocr_pages_skipped": 0,
        "complex_layout": result.get("complex_layout", False),
    }

def extract_document(file_obj, file_type: str, lang: str = None, progress=None) -> dict:
    """
    Extracts text from an uploaded file object.
    PDF: PyMuPDF text layer, with local PaddleOCR for scanned pages.
    PNG/JPG: local PaddleOCR. TXT: decoded directly.
    `lang` is the OCR language (one of settings.OCR_ALLOWED_LANGS; default OCR_LANG).
    Returns {"text", "method", "ocr_pages", "ocr_confidence", "page_count",
             "ocr_pages_skipped", "complex_layout", "truncated", "original_chars"}.
    Enforces a strict 50,000 character limit.
    """
    result = {"text": "", "method": "text", "ocr_pages": 0, "ocr_confidence": None,
              "page_count": 0, "ocr_pages_skipped": 0, "complex_layout": False, "vision_fallback_pages": 0}
    file_obj.seek(0)

    if file_type == 'PDF':
        try:
            # Read file bytes into memory for PyMuPDF
            file_bytes = file_obj.read()
            if not file_bytes:
                raise DocumentExtractionError("The uploaded PDF file is empty.")
            result = _extract_pdf(file_bytes, lang, progress)
        except pymupdf.FileDataError as exc:
            raise DocumentExtractionError(f"Corrupted or invalid PDF file: {str(exc)}") from exc
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError(f"Failed to extract text from PDF: {str(exc)}") from exc

    elif file_type in IMAGE_TYPES:
        file_bytes = file_obj.read()
        if not file_bytes:
            raise DocumentExtractionError("The uploaded image file is empty.")
        if progress:
            progress(0, 1)
        try:
            result = _extract_image(file_bytes, file_type, lang)
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError(f"Failed to run OCR on image: {str(exc)}") from exc

    elif file_type == 'TXT':
        try:
            raw_bytes = file_obj.read()
            if not raw_bytes:
                raise DocumentExtractionError("The uploaded TXT file is empty.")
            
            # Try utf-8 first, fallback to latin-1
            try:
                result["text"] = raw_bytes.decode('utf-8').strip()
            except UnicodeDecodeError:
                result["text"] = raw_bytes.decode('latin-1', errors='replace').strip()
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError(f"Failed to read TXT file: {str(exc)}") from exc
    else:
        raise DocumentExtractionError(f"Unsupported file type '{file_type}'.")

    text = result["text"]
    if not text.strip():
        raise DocumentExtractionError(
            "No readable text could be extracted from this document, even with local OCR. "
            "The scan may be blank, too low-resolution, or contain only graphics."
        )

    # Enforce the configured character limit (reported via result["truncated"])
    max_chars = getattr(settings, "DOCUMENT_MAX_CHARS", MAX_EXTRACTED_CHARS)
    result["original_chars"] = len(text)
    result["truncated"] = len(text) > max_chars
    if result["truncated"]:
        text = (
            text[:max_chars]
            + f"\n\n[Note: Document truncated at {max_chars:,} characters for on-premise memory protection]"
        )
    result["text"] = text
    return result

def extract_text_from_file(file_obj, file_type: str) -> str:
    """Backward-compatible helper returning only the extracted text."""
    return extract_document(file_obj, file_type)["text"]
