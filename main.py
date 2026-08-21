import logging
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, status

from config import get_settings
from models.schemas import (
    DuplicateDocumentResponse,
    HealthResponse,
    NotionTestResponse,
    TestDocumentResponse,
    UniqueDocumentResponse,
)
from services.document_service import DocumentService
from services.notion_service import NotionService, NotionServiceError
from services.pdf_service import PDFProcessingError, validate_pdf
from utils.hashing import calculate_file_hash


logger = logging.getLogger(__name__)
ALLOWED_PDF_CONTENT_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/octet-stream",
}


app = FastAPI(
    title="DocFlow AI",
    version="0.3.0",
    description="Phase 3: PDF processing with Notion-backed duplicate detection.",
)


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Confirm that the FastAPI application is running."""
    return HealthResponse(status="running", service="DocFlow AI")


@app.get("/notion/test", response_model=NotionTestResponse)
async def test_notion_connection() -> NotionTestResponse:
    """Verify the token and access to all configured Notion databases."""
    try:
        result = await NotionService().test_connection()
        return NotionTestResponse(
            success=True,
            message="Successfully connected to Notion and verified all three databases.",
            databases=result,
        )
    except NotionServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@app.post(
    "/documents/test",
    response_model=TestDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_test_document() -> TestDocumentResponse:
    """Create a minimal test row in DOCUMENT INBOX."""
    try:
        page = await NotionService().create_test_document()
        return TestDocumentResponse(
            success=True,
            message="Test document created in DOCUMENT INBOX.",
            page_id=page["id"],
            page_url=page.get("url"),
        )
    except NotionServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@app.post("/documents/upload", response_model=UniqueDocumentResponse | DuplicateDocumentResponse)
async def upload_document(
    file: UploadFile | None = File(default=None),
) -> UniqueDocumentResponse | DuplicateDocumentResponse:
    """Validate a PDF, prevent duplicates, then persist a unique document to Notion."""
    if file is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A PDF file is required.")

    filename = Path(file.filename or "").name
    if not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file needs a filename.")
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only PDF files are supported.")
    if file.content_type and file.content_type.lower() not in ALLOWED_PDF_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The uploaded file has an unsupported content type. Please upload a PDF.",
        )

    settings = get_settings()
    try:
        # Read at most one byte over the limit, avoiding an unbounded in-memory upload.
        file_bytes = await file.read(settings.max_upload_size_bytes + 1)
    except Exception as exc:
        logger.warning("Unable to read uploaded file %s: %s", filename, type(exc).__name__)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file could not be read.") from exc
    finally:
        await file.close()

    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded PDF is empty.")
    if len(file_bytes) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"The PDF exceeds the {settings.max_upload_size_mb} MB upload limit.",
        )

    file_hash = calculate_file_hash(file_bytes)
    try:
        validate_pdf(file_bytes, filename)
        document_result = await DocumentService().process_unique_document(
            file_bytes, filename, file_hash
        )
        if document_result["is_duplicate"]:
            existing_document_id = document_result.get("existing_document_id")
            if not existing_document_id:
                logger.error("Notion duplicate result did not include a page ID.")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Notion returned incomplete duplicate information.",
                )
            return DuplicateDocumentResponse(
                is_duplicate=True,
                message="This document has already been processed.",
                existing_document_id=existing_document_id,
                file_hash=file_hash,
                existing_document_name=document_result.get("existing_document_name"),
                existing_document_status=document_result.get("existing_document_status"),
            )

        return UniqueDocumentResponse(
            is_duplicate=False,
            message="New document processed successfully.",
            document_id=document_result["document_id"],
            filename=document_result["filename"],
            page_count=document_result["page_count"],
            text=document_result["extracted_text"],
            character_count=document_result["character_count"],
            file_hash=document_result["file_hash"],
            needs_human_review=document_result["needs_human_review"],
            text_extraction_method=document_result["text_extraction_method"],
            ocr_used=document_result["ocr_used"],
            analysis=document_result.get("analysis"),
        )
    except PDFProcessingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except NotionServiceError as exc:
        logger.error("Document duplicate check or Notion record creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Document processing could not safely complete because Notion is unavailable or misconfigured.",
        ) from exc
