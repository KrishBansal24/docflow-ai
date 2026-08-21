import asyncio
import logging
from typing import Any

from services.notion_service import NotionService
from services.pdf_service import process_pdf
from services.ai_service import AIService, AIServiceError
from services.ocr_service import OCRService, OCRServiceError

logger = logging.getLogger(__name__)


# A single lock makes the check-and-create operation atomic within one FastAPI
# process. A distributed lock or database constraint would be needed for multiple
# application instances, which is outside this hackathon MVP.
_document_creation_lock = asyncio.Lock()


def _try_create_ocr_service() -> OCRService | None:
    """Attempt to construct OCRService, returning None if the key is missing.

    OCR is an optional fallback. A missing API key must NOT prevent the
    DocumentService from starting or processing PDFs with embedded text.
    """
    try:
        return OCRService()
    except OCRServiceError as exc:
        logger.warning(
            "OCR service is unavailable (will be skipped for all requests): %s", exc
        )
        return None


class DocumentService:
    """Coordinate duplicate detection, PDF processing, and Notion persistence."""

    def __init__(self) -> None:
        self.notion_service = NotionService()
        self.ai_service = AIService()
        # OCR is optional — a missing Mistral key must not break non-OCR paths.
        self.ocr_service: OCRService | None = _try_create_ocr_service()

    async def process_unique_document(
        self, file_bytes: bytes, filename: str, file_hash: str
    ) -> dict[str, Any]:
        """Return an existing document or process and persist one new document."""
        async with _document_creation_lock:
            duplicate_result = await self.notion_service.check_duplicate_document(file_hash)
            if duplicate_result["is_duplicate"]:
                return duplicate_result

            processed_document = process_pdf(file_bytes, filename, file_hash)

            document_id = (await self.notion_service.create_processed_document(filename, file_hash))["id"]

            extracted_text = processed_document["extracted_text"]
            needs_human_review = processed_document["needs_human_review"]
            text_extraction_method = processed_document["text_extraction_method"]
            ocr_used = processed_document["ocr_used"]

            # ----------------------------------------------------------------
            # OCR fallback — ONLY triggered when embedded text was not found.
            # OCR errors must never affect documents that already have text.
            # ----------------------------------------------------------------
            if needs_human_review:
                if self.ocr_service is None:
                    logger.info(
                        "OCR skipped for %s (no Mistral key configured).", filename
                    )
                else:
                    try:
                        logger.info(
                            "No meaningful embedded text for %s — attempting Mistral OCR.", filename
                        )
                        ocr_text = await self.ocr_service.extract_text(file_bytes, filename)
                        if ocr_text.strip():
                            from services.pdf_service import is_meaningful_text
                            if is_meaningful_text(ocr_text):
                                extracted_text = ocr_text
                                needs_human_review = False
                                text_extraction_method = "ocr"
                                ocr_used = True
                                processed_document["extracted_text"] = ocr_text
                                processed_document["character_count"] = len(ocr_text)
                                processed_document["message"] = "PDF processed successfully using OCR"
                                logger.info("OCR successful for %s | chars=%d", filename, len(ocr_text))
                            else:
                                logger.warning(
                                    "OCR produced text for %s but quality check failed.", filename
                                )
                        else:
                            logger.warning("OCR returned empty text for %s.", filename)
                    except OCRServiceError as exc:
                        logger.warning("OCR fallback failed for %s: %s", filename, exc)
                        # needs_human_review stays True — that is already the correct state.

            processed_document["text_extraction_method"] = text_extraction_method
            processed_document["ocr_used"] = ocr_used
            processed_document["needs_human_review"] = needs_human_review

            logger.info(
                "Extraction complete for %s | method=%s | ocr_used=%s | needs_review=%s",
                filename,
                text_extraction_method,
                ocr_used,
                needs_human_review,
            )

            # ----------------------------------------------------------------
            # AI analysis — only for documents with usable text.
            # ----------------------------------------------------------------
            analysis = None

            if not needs_human_review:
                try:
                    analysis = self.ai_service.analyze_document(extracted_text)

                    if analysis.requires_human_approval:
                        needs_human_review = True
                        status_name = "Needs Human Review"
                    else:
                        status_name = "AI Analyzed"

                    await self.notion_service.update_document_analysis(document_id, analysis, status_name)

                except AIServiceError as exc:
                    logger.warning("AI analysis failed for %s: %s", filename, exc)
                    needs_human_review = True
                    await self.notion_service.update_document_analysis(document_id, None, "AI Analysis Failed")
            else:
                await self.notion_service.update_document_analysis(document_id, None, "Needs Human Review")

            processed_document["needs_human_review"] = needs_human_review

            return {
                "is_duplicate": False,
                "document_id": document_id,
                "analysis": analysis,
                **processed_document,
            }
