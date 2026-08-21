from fastapi import APIRouter, HTTPException, status
from models.schemas import HealthResponse, NotionTestResponse
from services.notion.client import NotionClient, NotionServiceError

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Confirm that the FastAPI application is running."""
    return HealthResponse(status="running", service="DocFlow AI")


@router.get("/notion/test", response_model=NotionTestResponse)
async def test_notion_connection() -> NotionTestResponse:
    """Verify the token and access to all configured Notion databases."""
    try:
        result = await NotionClient().test_connection()
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
