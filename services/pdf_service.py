import logging
from typing import Any

import pymupdf

from utils.hashing import calculate_file_hash


logger = logging.getLogger(__name__)


class PDFProcessingError(Exception):
    """A safe, user-facing error raised when a PDF cannot be processed."""


def process_pdf(file_bytes: bytes, filename: str, file_hash: str | None = None) -> dict[str, Any]:
    """Open a PDF in memory and return its basic extracted information.

    PyMuPDF is used as the final validation step, so a file merely named
    ``.pdf`` is rejected when it is not an actual readable PDF document.
    """
    document: pymupdf.Document | None = None
    try:
        document = pymupdf.open(stream=file_bytes, filetype="pdf")
        if not document.is_pdf:
            raise PDFProcessingError("The uploaded file is not a valid PDF.")
        if document.needs_pass:
            raise PDFProcessingError("The PDF is password-protected and cannot be processed.")

        extracted_text = "\n".join(page.get_text("text") for page in document)
        character_count = len(extracted_text)
        needs_human_review = character_count == 0

        return {
            "filename": filename,
            "page_count": document.page_count,
            "extracted_text": extracted_text,
            "character_count": character_count,
            "file_hash": file_hash or calculate_file_hash(file_bytes),
            "needs_human_review": needs_human_review,
            "message": (
                "PDF is valid but contains no readable text. OCR may be required."
                if needs_human_review
                else "PDF processed successfully"
            ),
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
