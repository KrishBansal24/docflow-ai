import asyncio
from typing import Any

from services.notion_service import NotionService
from services.pdf_service import process_pdf


# A single lock makes the check-and-create operation atomic within one FastAPI
# process. A distributed lock or database constraint would be needed for multiple
# application instances, which is outside this hackathon MVP.
_document_creation_lock = asyncio.Lock()


class DocumentService:
    """Coordinate duplicate detection, PDF processing, and Notion persistence."""

    def __init__(self) -> None:
        self.notion_service = NotionService()

    async def process_unique_document(
        self, file_bytes: bytes, filename: str, file_hash: str
    ) -> dict[str, Any]:
        """Return an existing document or process and persist one new document."""
        async with _document_creation_lock:
            duplicate_result = await self.notion_service.check_duplicate_document(file_hash)
            if duplicate_result["is_duplicate"]:
                return duplicate_result

            processed_document = process_pdf(file_bytes, filename, file_hash)
            page = await self.notion_service.create_processed_document(filename, file_hash)
            return {
                "is_duplicate": False,
                "document_id": page["id"],
                **processed_document,
            }
