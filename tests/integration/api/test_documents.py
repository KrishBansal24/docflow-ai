import unittest
import pymupdf
from fastapi.testclient import TestClient

import main

class FakeDocumentService:
    result: dict[str, object] = {}

    async def process_unique_document(
        self, file_bytes: bytes, filename: str, file_hash: str
    ) -> dict[str, object]:
        return self.result

class TestDocumentsAPI(unittest.TestCase):
    def setUp(self) -> None:
        import api.documents
        self.original_document_service = api.documents.DocumentService
        api.documents.DocumentService = FakeDocumentService
        self.client = TestClient(main.app)
        document = pymupdf.open()
        document.new_page().insert_text((72, 72), "Invoice total: 123")
        self.pdf_bytes = document.tobytes()
        document.close()

    def tearDown(self) -> None:
        import api.documents
        api.documents.DocumentService = self.original_document_service

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

if __name__ == "__main__":
    unittest.main()
