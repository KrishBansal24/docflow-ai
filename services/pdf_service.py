import logging
import re
from typing import Any

import pymupdf

from config import get_settings
from utils.hashing import calculate_file_hash


logger = logging.getLogger(__name__)

# A reasonable minimum: a PDF with fewer than this many alphanumeric characters
# after stripping whitespace is treated as having no meaningful text.
_DEFAULT_MIN_ALPHANUMERIC_CHARS = 50
# If more than this fraction of non-whitespace characters are alphanumeric/numeric
# the text is considered meaningful (guards against garbled □□□□ glyphs).
_DEFAULT_MIN_ALPHANUMERIC_RATIO = 0.30


class PDFProcessingError(Exception):
    """A safe, user-facing error raised when a PDF cannot be processed."""


def _open_valid_pdf(file_bytes: bytes, filename: str) -> pymupdf.Document:
    """Open and validate a PDF, returning an open document to the caller."""
    try:
        document = pymupdf.open(stream=file_bytes, filetype="pdf")
        if not document.is_pdf:
            document.close()
            raise PDFProcessingError("The uploaded file is not a valid PDF.")
        if document.needs_pass:
            document.close()
            raise PDFProcessingError("The PDF is password-protected and cannot be processed.")
        return document
    except PDFProcessingError:
        raise
    except Exception as exc:
        logger.warning("PDF validation failed for %s: %s", filename, type(exc).__name__)
        raise PDFProcessingError(
            "The uploaded file could not be opened as a valid PDF."
        ) from exc


def validate_pdf(file_bytes: bytes, filename: str) -> None:
    """Verify that bytes represent an accessible PDF without extracting text."""
    document = _open_valid_pdf(file_bytes, filename)
    document.close()


def is_meaningful_text(text: str) -> bool:
    """Return True if the text contains enough readable alphanumeric content.

    Guards against:
    - Whitespace-only content (newlines, form-feeds, spaces).
    - Garbled glyph strings (□□□□, ▪▪▪▪) where few characters are alphanumeric.

    The thresholds are intentionally conservative to avoid rejecting real invoices
    with sparse text layouts.
    """
    settings = get_settings()
    min_chars = getattr(settings, "min_embedded_text_length", _DEFAULT_MIN_ALPHANUMERIC_CHARS)
    min_ratio = getattr(settings, "min_text_alphanumeric_ratio", _DEFAULT_MIN_ALPHANUMERIC_RATIO)

    # Count alphanumeric characters only
    alphanumeric_chars = re.findall(r"[a-zA-Z0-9]", text)
    alphanumeric_count = len(alphanumeric_chars)

    if alphanumeric_count < min_chars:
        logger.debug(
            "Text quality check: only %d alphanumeric chars (min %d) — not meaningful",
            alphanumeric_count,
            min_chars,
        )
        return False

    # Check ratio against non-whitespace chars to catch garbled glyphs
    non_whitespace = re.sub(r"\s+", "", text)
    if non_whitespace:
        ratio = alphanumeric_count / len(non_whitespace)
        if ratio < min_ratio:
            logger.debug(
                "Text quality check: alphanumeric ratio %.2f (min %.2f) — not meaningful",
                ratio,
                min_ratio,
            )
            return False

    return True


def process_pdf(file_bytes: bytes, filename: str, file_hash: str | None = None) -> dict[str, Any]:
    """Extract readable text and metadata from a previously validated PDF.

    Returns a dict with:
    - filename, page_count, extracted_text, character_count, file_hash
    - needs_human_review: True if no meaningful embedded text was found
    - text_extraction_method: 'embedded' or 'none' (OCR is handled upstream)
    - message: human-readable status
    """
    document: pymupdf.Document | None = None
    try:
        document = _open_valid_pdf(file_bytes, filename)
        page_count = document.page_count

        # Extract text from ALL pages and join with a separator
        page_texts = []
        for page in document:
            page_text = page.get_text("text")
            if page_text:
                page_texts.append(page_text)
        extracted_text = "\n".join(page_texts)
        character_count = len(extracted_text)

        embedded_is_meaningful = is_meaningful_text(extracted_text)

        logger.info(
            "Processing %s | pages=%d | embedded_chars=%d | meaningful=%s",
            filename,
            page_count,
            character_count,
            embedded_is_meaningful,
        )

        if embedded_is_meaningful:
            return {
                "filename": filename,
                "page_count": page_count,
                "extracted_text": extracted_text,
                "character_count": character_count,
                "file_hash": file_hash or calculate_file_hash(file_bytes),
                "needs_human_review": False,
                "text_extraction_method": "embedded",
                "ocr_used": False,
                "message": "PDF processed successfully",
            }
        else:
            return {
                "filename": filename,
                "page_count": page_count,
                "extracted_text": "",
                "character_count": 0,
                "file_hash": file_hash or calculate_file_hash(file_bytes),
                "needs_human_review": True,
                "text_extraction_method": "none",
                "ocr_used": False,
                "message": "PDF is valid but contains no readable text. OCR may be required.",
            }

    except PDFProcessingError:
        raise
    except Exception as exc:
        logger.warning("PDF processing failed for %s: %s", filename, type(exc).__name__)
        raise PDFProcessingError(
            "The uploaded file could not be opened as a valid PDF."
        ) from exc
    finally:
        if document is not None:
            document.close()
