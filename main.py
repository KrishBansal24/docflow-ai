from fastapi import FastAPI, HTTPException, status

from models.schemas import HealthResponse, NotionTestResponse, TestDocumentResponse
from services.notion_service import NotionService, NotionServiceError


app = FastAPI(
    title="DocFlow AI",
    version="0.1.0",
    description="Phase 1: FastAPI to Notion connection test.",
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
