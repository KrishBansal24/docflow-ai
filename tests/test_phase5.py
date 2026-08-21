import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pymupdf
from fastapi.testclient import TestClient

import main
from models.schemas import DocumentAnalysisResult
from models.workflow import DocumentStatus
from services.ai_service import AIServiceError
from services.ocr_service import OCRServiceError
from services.notion_service import NotionService, NotionServiceError


def _make_text_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_whitespace_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


class Phase5Tests(unittest.TestCase):
    """Phase 5: Document workflow status lifecycle tests."""

    def setUp(self) -> None:
        self.client = TestClient(main.app)

        self.pdf_bytes = _make_text_pdf(
            "Invoice Number IN-2025-001\nInvoice Date: 30 December 2025\n"
            "Total Amount: USD 123.00 for ABC Corp Ltd\nOrder: 402-1234567"
        )

        self.mock_notion = MagicMock(spec=NotionService)
        self.mock_notion.check_duplicate_document = AsyncMock(
            return_value={"is_duplicate": False}
        )
        self.mock_notion.create_processed_document = AsyncMock(
            return_value={"id": "fake-page-id"}
        )
        self.mock_notion.update_document_analysis = AsyncMock(
            return_value={"id": "fake-page-id"}
        )

        self.notion_patcher = patch(
            "services.document_service.NotionService",
            return_value=self.mock_notion,
        )
        self.notion_patcher.start()

        self.mock_ocr = MagicMock()
        self.mock_ocr.extract_text = AsyncMock(
            return_value="Invoice Number OCR-001\nAmount: INR 999\nVendor: OcrCorp\nDate: 2025-06-01"
        )
        self.ocr_patcher = patch(
            "services.document_service.OCRService",
            return_value=self.mock_ocr,
        )
        self.ocr_patcher.start()

    def tearDown(self) -> None:
        self.notion_patcher.stop()
        self.ocr_patcher.stop()

    # ------------------------------------------------------------------
    # TEST 1: High-confidence AI → AI Analyzed
    # ------------------------------------------------------------------
    @patch("services.document_service.AIService")
    def test_high_confidence_workflow_status(self, mock_ai_class: MagicMock) -> None:
        mock_ai = mock_ai_class.return_value
        mock_ai.analyze_document.return_value = DocumentAnalysisResult(
            document_type="Supplier Invoice",
            vendor_or_company="ABC Corp",
            amount=123.0,
            confidence=0.95,
            requires_human_approval=False,
        )

        response = self.client.post(
            "/documents/upload",
            files={"file": ("invoice.pdf", self.pdf_bytes, "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["workflow_status"], DocumentStatus.AI_ANALYZED.value)
        self.assertFalse(data["needs_human_review"])
        self.assertIsNotNone(data["analysis"])

        self.mock_notion.update_document_analysis.assert_called_once_with(
            "fake-page-id",
            mock_ai.analyze_document.return_value,
            DocumentStatus.AI_ANALYZED.value,
        )

    # ------------------------------------------------------------------
    # TEST 2: Low-confidence AI → Needs Human Review
    # ------------------------------------------------------------------
    @patch("services.document_service.AIService")
    def test_low_confidence_workflow_status(self, mock_ai_class: MagicMock) -> None:
        mock_ai = mock_ai_class.return_value
        mock_ai.analyze_document.return_value = DocumentAnalysisResult(
            document_type="Unknown",
            confidence=0.3,
            requires_human_approval=True,
        )

        response = self.client.post(
            "/documents/upload",
            files={"file": ("invoice.pdf", self.pdf_bytes, "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["workflow_status"], DocumentStatus.NEEDS_HUMAN_REVIEW.value)
        self.assertTrue(data["needs_human_review"])

    # ------------------------------------------------------------------
    # TEST 3: AI failure → AI Analysis Failed
    # ------------------------------------------------------------------
    @patch("services.document_service.AIService")
    def test_ai_failure_workflow_status(self, mock_ai_class: MagicMock) -> None:
        mock_ai = mock_ai_class.return_value
        mock_ai.analyze_document.side_effect = AIServiceError("Model unavailable")

        response = self.client.post(
            "/documents/upload",
            files={"file": ("invoice.pdf", self.pdf_bytes, "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["workflow_status"], DocumentStatus.AI_ANALYSIS_FAILED.value)
        self.assertTrue(data["needs_human_review"])
        self.assertIsNone(data.get("analysis"))

    # ------------------------------------------------------------------
    # TEST 4: Duplicate document — no reprocessing
    # ------------------------------------------------------------------
    @patch("services.document_service.AIService")
    def test_duplicate_document_no_reprocessing(self, mock_ai_class: MagicMock) -> None:
        self.mock_notion.check_duplicate_document = AsyncMock(
            return_value={
                "is_duplicate": True,
                "existing_document_id": "dup-page-id",
                "existing_document_name": "invoice.pdf",
                "existing_document_status": DocumentStatus.AI_ANALYZED.value,
            }
        )

        response = self.client.post(
            "/documents/upload",
            files={"file": ("invoice.pdf", self.pdf_bytes, "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["is_duplicate"])
        self.assertEqual(data["existing_document_id"], "dup-page-id")

        # AI and OCR must not be called for duplicates
        mock_ai_class.return_value.analyze_document.assert_not_called()
        self.mock_ocr.extract_text.assert_not_called()
        self.mock_notion.create_processed_document.assert_not_called()

    # ------------------------------------------------------------------
    # TEST 5: Missing optional Notion property — workflow continues
    # ------------------------------------------------------------------
    @patch("services.document_service.AIService")
    def test_missing_optional_notion_property(self, mock_ai_class: MagicMock) -> None:
        """Even if update_document_analysis returns empty (missing properties), workflow succeeds."""
        mock_ai = mock_ai_class.return_value
        mock_ai.analyze_document.return_value = DocumentAnalysisResult(
            document_type="Invoice",
            confidence=0.9,
            requires_human_approval=False,
        )
        # Simulate Notion returning empty dict (all optional properties missing)
        self.mock_notion.update_document_analysis = AsyncMock(return_value={})

        response = self.client.post(
            "/documents/upload",
            files={"file": ("invoice.pdf", self.pdf_bytes, "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["workflow_status"], DocumentStatus.AI_ANALYZED.value)

    # ------------------------------------------------------------------
    # TEST 6: Missing Notion status option — Notion update error caught
    # ------------------------------------------------------------------
    @patch("services.document_service.AIService")
    def test_notion_status_update_failure_does_not_crash(self, mock_ai_class: MagicMock) -> None:
        """If Notion rejects a status update, the error propagates as NotionServiceError
        but the API returns a 502 (existing behavior) rather than crashing."""
        mock_ai = mock_ai_class.return_value
        mock_ai.analyze_document.return_value = DocumentAnalysisResult(
            document_type="Invoice",
            confidence=0.9,
            requires_human_approval=False,
        )
        self.mock_notion.update_document_analysis = AsyncMock(
            side_effect=NotionServiceError("Status option 'AI Analyzed' not found")
        )

        response = self.client.post(
            "/documents/upload",
            files={"file": ("invoice.pdf", self.pdf_bytes, "application/pdf")},
        )

        # Notion failure → 502 (existing error handling in main.py)
        self.assertEqual(response.status_code, 502)

    # ------------------------------------------------------------------
    # TEST 7: Notion API down → 502
    # ------------------------------------------------------------------
    @patch("services.document_service.AIService")
    def test_notion_api_failure(self, mock_ai_class: MagicMock) -> None:
        self.mock_notion.check_duplicate_document = AsyncMock(
            side_effect=NotionServiceError("Connection refused")
        )

        response = self.client.post(
            "/documents/upload",
            files={"file": ("invoice.pdf", self.pdf_bytes, "application/pdf")},
        )

        self.assertEqual(response.status_code, 502)

    # ------------------------------------------------------------------
    # TEST 8: OCR-produced text → same workflow as embedded
    # ------------------------------------------------------------------
    @patch("services.document_service.AIService")
    def test_ocr_text_workflow(self, mock_ai_class: MagicMock) -> None:
        mock_ai = mock_ai_class.return_value
        mock_ai.analyze_document.return_value = DocumentAnalysisResult(
            document_type="Invoice",
            confidence=0.85,
            requires_human_approval=False,
        )

        pdf = _make_whitespace_pdf()  # No embedded text → triggers OCR
        response = self.client.post(
            "/documents/upload",
            files={"file": ("scan.pdf", pdf, "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ocr_used"])
        self.assertEqual(data["text_extraction_method"], "ocr")
        self.assertEqual(data["workflow_status"], DocumentStatus.AI_ANALYZED.value)

    # ------------------------------------------------------------------
    # TEST 9: Embedded text PDF → correct workflow status
    # ------------------------------------------------------------------
    @patch("services.document_service.AIService")
    def test_embedded_text_workflow(self, mock_ai_class: MagicMock) -> None:
        mock_ai = mock_ai_class.return_value
        mock_ai.analyze_document.return_value = DocumentAnalysisResult(
            document_type="Supplier Invoice",
            vendor_or_company="Amazon",
            confidence=0.92,
            requires_human_approval=False,
        )

        response = self.client.post(
            "/documents/upload",
            files={"file": ("invoice.pdf", self.pdf_bytes, "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["text_extraction_method"], "embedded")
        self.assertFalse(data["ocr_used"])
        self.assertEqual(data["workflow_status"], DocumentStatus.AI_ANALYZED.value)
        self.assertFalse(data["needs_human_review"])


class DocumentStatusEnumTests(unittest.TestCase):
    """Verify the DocumentStatus enum itself."""

    def test_all_status_values_are_strings(self) -> None:
        for member in DocumentStatus:
            self.assertIsInstance(member.value, str)

    def test_expected_members_exist(self) -> None:
        expected = {"Processing", "AI Analyzed", "Needs Human Review", "AI Analysis Failed", "Approved", "Rejected"}
        actual = {s.value for s in DocumentStatus}
        self.assertEqual(actual, expected)

    def test_enum_is_str_subclass(self) -> None:
        """DocumentStatus(str, Enum) allows using members directly as strings."""
        self.assertEqual(DocumentStatus.PROCESSING, "Processing")


if __name__ == "__main__":
    unittest.main()
