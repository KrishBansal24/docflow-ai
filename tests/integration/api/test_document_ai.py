import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pymupdf
from fastapi.testclient import TestClient

import main
from models.schemas import DocumentAnalysisResult
from services.ai_service import AIServiceError
from services.notion import DocumentNotionService, RunLogNotionService


class Phase4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)
        document = pymupdf.open()
        document.new_page().insert_text(
            (72, 72),
            "Invoice Number IN-2025-001\nInvoice Date: 30 December 2025\n"
            "Total Amount: USD 123.00 for ABC Corp Ltd\nOrder: 402-1234567",
        )
        self.pdf_bytes = document.tobytes()
        document.close()
        
        # A mock for the Notion Service to pretend everything works
        self.mock_notion = MagicMock(spec=DocumentNotionService)
        self.mock_notion.check_duplicate_document = AsyncMock(return_value={"is_duplicate": False})
        self.mock_notion.create_processed_document = AsyncMock(return_value={"id": "fake-page-id"})
        self.mock_notion.update_document_properties = AsyncMock()

        self.notion_patcher = patch("services.document_service.DocumentNotionService", return_value=self.mock_notion)
        self.notion_patcher.start()
        
        self.mock_run_log = MagicMock(spec=RunLogNotionService)
        self.mock_run_log.create_run_log_entry = AsyncMock()
        self.run_log_patcher = patch(
            "services.document_service.RunLogNotionService", return_value=self.mock_run_log
        )
        self.run_log_patcher.start()
        
        self.mock_approval_notion = MagicMock()
        self.mock_approval_notion.check_existing_approval = AsyncMock(return_value=None)
        self.mock_approval_notion.create_approval_entry = AsyncMock(return_value={"id": "fake-approval-id"})
        self.mock_approval_notion.update_approval_decision = AsyncMock(return_value={"id": "fake-approval-id"})
        self.approval_patcher = patch("services.approval_service.ApprovalNotionService", return_value=self.mock_approval_notion)
        self.approval_patcher.start()

        self.mock_ocr = MagicMock()
        # OCR mock returns meaningful text so it passes the quality check
        self.mock_ocr.extract_text = AsyncMock(
            return_value=(
                "Invoice Number OCR-001\nDate: 01 January 2025\n"
                "Vendor: OCR Corp International\nTotal Amount: INR 999.00"
            )
        )
        self.ocr_patcher = patch("services.document_service.OCRService", return_value=self.mock_ocr)
        self.ocr_patcher.start()

    def tearDown(self) -> None:
        self.notion_patcher.stop()
        self.run_log_patcher.stop()
        self.approval_patcher.stop()
        self.ocr_patcher.stop()

    @patch("services.document_service.AIService")
    def test_successful_ai_analysis(self, mock_ai_class: MagicMock) -> None:
        mock_ai_instance = mock_ai_class.return_value
        fake_analysis = DocumentAnalysisResult(
            document_type="Supplier Invoice",
            vendor_or_company="ABC Corp",
            amount=123.00,
            )
        mock_ai_instance.analyze_document.return_value = fake_analysis

        response = self.client.post(
            "/documents/upload",
            files={"file": ("invoice.pdf", self.pdf_bytes, "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["is_duplicate"])
        self.assertEqual(data["document_id"], "fake-page-id")
        self.assertEqual(data["processing_status"], "AI Analyzed")
        self.assertEqual(data["analysis"]["document_type"], "Supplier Invoice")
        self.assertEqual(data["analysis"]["amount"], 123.0)
        
        # Verify it attempted to update Notion with "AI Analyzed"
        self.mock_notion.update_document_properties.assert_called_once_with(
            "fake-page-id", "AI Analyzed", fake_analysis, custom_title=None
        )

    @patch("services.document_service.AIService")
    def test_low_confidence_ai_analysis(self, mock_ai_class: MagicMock) -> None:
        mock_ai_instance = mock_ai_class.return_value
        fake_analysis = DocumentAnalysisResult(
            document_type="Unknown",
            )
        mock_ai_instance.analyze_document.return_value = fake_analysis

        response = self.client.post(
            "/documents/upload",
            files={"file": ("invoice.pdf", self.pdf_bytes, "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["processing_status"], "AI Analyzed")
        
        self.mock_notion.update_document_properties.assert_called_once_with(
            "fake-page-id", "AI Analyzed", fake_analysis, custom_title=None
        )

    @patch("services.document_service.AIService")
    def test_ai_failure_fallback(self, mock_ai_class: MagicMock) -> None:
        mock_ai_instance = mock_ai_class.return_value
        mock_ai_instance.analyze_document.side_effect = AIServiceError("API down")

        response = self.client.post(
            "/documents/upload",
            files={"file": ("invoice.pdf", self.pdf_bytes, "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["processing_status"], "AI Analysis Failed")
        self.assertIsNone(data.get("analysis"))
        
        self.mock_notion.update_document_properties.assert_called_once_with(
            "fake-page-id", "AI Analysis Failed", None
        )

if __name__ == "__main__":
    unittest.main()
