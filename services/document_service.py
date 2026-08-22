import asyncio
import logging
from typing import Any

from config import get_settings

from models.workflow import ProcessingStatus, DecisionStatus
from models.approval import ApprovalDecision
from services.notion import DocumentNotionService, RunLogNotionService
from services.notion.directory import DirectoryNotionService
from services.pdf_service import process_pdf
from services.ai_service import AIService, AIServiceError
from services.ocr_service import OCRService, OCRServiceError
from services.approval_service import ApprovalService, ApprovalServiceError

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
        self.document_notion_service = DocumentNotionService()
        self.run_log_notion_service = RunLogNotionService()
        self.directory_notion_service = DirectoryNotionService()
        self.ai_service = AIService()
        self.approval_service = ApprovalService()
        # OCR is optional — a missing Mistral key must not break non-OCR paths.
        self.ocr_service: OCRService | None = _try_create_ocr_service()

    async def process_unique_document(
        self, file_bytes: bytes, filename: str, file_hash: str
    ) -> dict[str, Any]:
        """Return an existing document or process and persist one new document."""
        async with _document_creation_lock:
            duplicate_result = await self.document_notion_service.check_duplicate_document(file_hash)
            if duplicate_result["is_duplicate"]:
                return duplicate_result

            processed_document = process_pdf(file_bytes, filename, file_hash)

            document_id = (await self.document_notion_service.create_processed_document(filename, file_hash))["id"]
            logger.info("[WORKFLOW] Document created in Notion: %s (id=%s)", filename, document_id)
            await self.run_log_notion_service.create_run_log_entry("Document Received", "Success", f"Started processing {filename}", document_id, event_type="Upload")

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

            processed_document["text_extraction_method"] = text_extraction_method
            processed_document["ocr_used"] = ocr_used
            processed_document["needs_human_review"] = needs_human_review

            logger.info(
                "[WORKFLOW] Extraction complete for %s | method=%s | ocr_used=%s | needs_review=%s",
                filename, text_extraction_method, ocr_used, needs_human_review,
            )

            # ----------------------------------------------------------------
            # AI analysis — only for documents with usable text.
            # ----------------------------------------------------------------
            analysis = None
            processing_status: ProcessingStatus
            decision_status = DecisionStatus.PENDING_DECISION
            approval_decision = ApprovalDecision.PENDING_DECISION

            if not needs_human_review:
                try:
                    routing_map = await self.directory_notion_service.get_department_routing()
                    available_departments = list(routing_map.keys()) if routing_map else None
                    
                    analysis = self.ai_service.analyze_document(extracted_text, available_departments)
                    processing_status = ProcessingStatus.AI_ANALYZED
                    logger.info(
                        "[WORKFLOW] AI analysis completed for %s",
                        filename
                    )

                    custom_title = None
                    if filename.startswith("whatsapp_upload_"):
                        sender = filename.replace("whatsapp_upload_", "").split(".")[0]
                        dept = analysis.departments[0] if analysis.departments else "Unknown"
                        doc_type = analysis.document_type or "Document"
                        custom_title = f"{doc_type} from {dept} (Sender: {sender})"

                    await self.document_notion_service.update_document_properties(
                        document_id, processing_status.value, analysis, custom_title=custom_title
                    )
                    await self.run_log_notion_service.create_run_log_entry("AI Extraction", "Success", "AI successfully extracted document data.", document_id, event_type="AI")

                except AIServiceError as exc:
                    logger.warning("[WORKFLOW] AI analysis failed for %s: %s", filename, exc)
                    processing_status = ProcessingStatus.AI_ANALYSIS_FAILED
                    await self.document_notion_service.update_document_properties(
                        document_id, processing_status.value, None
                    )
                    await self.run_log_notion_service.create_run_log_entry("AI Extraction", "Failed", f"AI analysis failed: {exc}", document_id, event_type="AI")
            else:
                processing_status = ProcessingStatus.NEEDS_HUMAN_REVIEW
                await self.run_log_notion_service.create_run_log_entry("Text Extraction", "Failed", "Could not extract readable text from document.", document_id, event_type="System")
                logger.info("[WORKFLOW] No usable text for %s — human review required", filename)
                await self.document_notion_service.update_document_properties(
                    document_id, processing_status.value, None
                )

            # ----------------------------------------------------------------
            # Human Approval Queue Integration (Phase 6)
            # Universal Rule: EVERY unique document must enter the Approval Queue
            # ----------------------------------------------------------------
            try:
                if processing_status == ProcessingStatus.AI_ANALYZED:
                    suggested_approver = analysis.departments[0] if (analysis and analysis.departments) else "Unknown"
                    await self.approval_service.queue_document_for_review(
                        document_id=document_id,
                        document_name=filename,
                        reason="Review AI Extraction",
                        suggested_recipient=suggested_approver,
                        priority=analysis.priority if analysis else None
                    )
                else:
                    reason = "No Usable Text / OCR Failed" if processing_status == ProcessingStatus.NEEDS_HUMAN_REVIEW else "AI Analysis Failed"
                    await self.approval_service.queue_document_for_review(
                        document_id=document_id,
                        document_name=filename,
                        reason=reason,
                        priority=None
                    )
            except ApprovalServiceError as exc:
                logger.error("[WORKFLOW] Failed to queue document for approval: %s", exc)
                # We log the error but don't crash the upload flow; the document is still in inbox.

            logger.info(
                "[WORKFLOW] Final status for %s: %s", filename, processing_status.value
            )

            # Clean up the output dictionary to only include what's requested
            processed_document.pop("needs_human_review", None)

            return {
                "is_duplicate": False,
                "document_id": document_id,
                "analysis": analysis,
                "processing_status": processing_status.value,
                "decision_status": decision_status.value,
                "approval_decision": approval_decision.value,
                **processed_document,
            }
