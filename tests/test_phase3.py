import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pymupdf
from fastapi.testclient import TestClient

import main
from services.notion_service import NotionService


DOCUMENT_INBOX_SCHEMA = {
    "id": "source-id",
    "properties": {
        "File Hash": {"type": "rich_text"},
        "Document Name": {"type": "title"},
        "Processing Status": {"type": "status", "status": {"options": [{"name": "Processing"}]}},
        "Decision Status": {"type": "status", "status": {"options": [{"name": "Pending Decision"}]}},
    },
}


class FakeDocumentService:
    result: dict[str, object] = {}

    async def process_unique_document(
        self, file_bytes: bytes, filename: str, file_hash: str
    ) -> dict[str, object]:
        return self.result


class Phase3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_document_service = main.DocumentService
        main.DocumentService = FakeDocumentService
        self.client = TestClient(main.app)
        document = pymupdf.open()
        document.new_page().insert_text((72, 72), "Invoice total: 123")
        self.pdf_bytes = document.tobytes()
        document.close()

    def tearDown(self) -> None:
        main.DocumentService = self.original_document_service

    def test_unique_document_response(self) -> None:
        FakeDocumentService.result = {
            "is_duplicate": False,
            "document_id": "new-page",
            "filename": "invoice.pdf",
            "page_count": 1,
            "extracted_text": "Invoice total: 123\n",
            "character_count": 19,
            "file_hash": "a" * 64,
            "needs_human_review": False,
            "text_extraction_method": "embedded",
            "ocr_used": False,
            "processing_status": "AI Analyzed",
            "decision_status": "Pending Decision",
            "approval_decision": "Pending Decision",
            "message": "PDF processed successfully",
        }

        response = self.client.post(
            "/documents/upload",
            files={"file": ("invoice.pdf", self.pdf_bytes, "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_duplicate"])
        self.assertEqual(response.json()["document_id"], "new-page")

    def test_duplicate_document_response(self) -> None:
        FakeDocumentService.result = {
            "is_duplicate": True,
            "existing_document_id": "existing-page",
            "existing_document_name": "Prior invoice",
            "existing_decision_status": "Processing",
        }

        response = self.client.post(
            "/documents/upload",
            files={"file": ("invoice-copy.pdf", self.pdf_bytes, "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_duplicate"])
        self.assertEqual(response.json()["existing_document_id"], "existing-page")

    def test_invalid_pdf_is_rejected_before_document_workflow(self) -> None:
        response = self.client.post(
            "/documents/upload",
            files={"file": ("fake.pdf", b"not a PDF", "application/pdf")},
        )

        self.assertEqual(response.status_code, 422)

    def test_duplicate_query_uses_exact_file_hash_filter(self) -> None:
        service = object.__new__(NotionService)
        service.settings = SimpleNamespace(document_inbox_id="database-id")
        service._get_data_source = AsyncMock(return_value=DOCUMENT_INBOX_SCHEMA)
        service._request = AsyncMock(return_value={"results": []})

        result = asyncio.run(service.check_duplicate_document("a" * 64))

        self.assertEqual(result, {"is_duplicate": False})
        request_json = service._request.call_args.kwargs["json"]
        self.assertEqual(request_json["filter"]["property"], "File Hash")
        self.assertEqual(request_json["filter"]["rich_text"]["equals"], "a" * 64)


if __name__ == "__main__":
    unittest.main()
