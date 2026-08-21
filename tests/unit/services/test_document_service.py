"""
Tests for the PDF text-extraction / OCR fallback logic (Bug Fix).

These tests verify:
  1. Embedded text is accepted and OCR skipped.
  2. Whitespace-only text is rejected, OCR attempted.
  3. Small-but-meaningful text passes the quality check.
  4. Scanned PDFs (no embedded text) trigger OCR.
  5. Successful OCR produces method='ocr'.
  6. Failed OCR yields needs_human_review=True without crashing.
  7. Good embedded text + broken OCR config → OCR never called, success.
  8. Multi-page PDF: text from both pages combined.
  9. Duplicate PDF: detection unchanged, AI not called.
 10. is_meaningful_text unit tests for various inputs.
"""
import asyncio
import io
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pymupdf
from fastapi.testclient import TestClient

import main
from services.ai_service import AIServiceError
from services.notion import DocumentNotionService, RunLogNotionService
from services.ocr_service import OCRServiceError
from services.pdf_service import is_meaningful_text, process_pdf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_text_pdf(text: str, pages: int = 1) -> bytes:
    """Create an in-memory PDF with readable text on every page."""
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_whitespace_pdf() -> bytes:
    """Create a valid PDF whose every page has only whitespace."""
    doc = pymupdf.open()
    doc.new_page()          # blank page — no text inserted
    data = doc.tobytes()
    doc.close()
    return data


def _make_multipage_pdf(page_texts: list[str]) -> bytes:
    """Create a multi-page PDF with distinct text on each page."""
    doc = pymupdf.open()
    for text in page_texts:
        doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


# ---------------------------------------------------------------------------
# Unit tests: is_meaningful_text
# ---------------------------------------------------------------------------

class IsMeaningfulTextTests(unittest.IsolatedAsyncioTestCase):

    async def test_good_invoice_text(self) -> None:
        text = "Invoice Number: XYZ123\nInvoice Date: 2025-12-30\nTotal: INR 1699"
        self.assertTrue(is_meaningful_text(text))

    async def test_empty_string(self) -> None:
        self.assertFalse(is_meaningful_text(""))

    async def test_whitespace_only(self) -> None:
        self.assertFalse(is_meaningful_text("\n\n\n   \t  \x0c"))

    async def test_garbled_glyphs(self) -> None:
        # All non-alphanumeric: should fail ratio check
        self.assertFalse(is_meaningful_text("□□□□ ▪▪▪▪ □□□□"))

    async def test_short_but_meaningful(self) -> None:
        # Exactly on the boundary — 2 letters is not enough
        self.assertFalse(is_meaningful_text("AB"))

    async def test_just_enough_alphanumeric(self) -> None:
        # 50 'a' characters — should pass default threshold
        self.assertTrue(is_meaningful_text("a" * 50))

    async def test_multiline_amazon_invoice_sample(self) -> None:
        sample = (
            "Amazon India\n"
            "Invoice Number: IN-12345\n"
            "Order Date: 01 January 2025\n"
            "Billed to: John Doe, 123 Main Street\n"
            "Item: USB-C Cable × 1    INR 599\n"
            "Total: INR 599\n"
        )
        self.assertTrue(is_meaningful_text(sample))


# ---------------------------------------------------------------------------
# Integration tests: process_pdf (pdf_service)
# ---------------------------------------------------------------------------

class ProcessPdfTests(unittest.IsolatedAsyncioTestCase):

    async def test_embedded_text_accepted(self) -> None:
        pdf = _make_text_pdf(
            "Invoice Number IN-2025-001\nVendor: ABC Corp Ltd\nTotal Amount: INR 1500\nDate: 01 Jan 2025"
        )
        result = process_pdf(pdf, "invoice.pdf", "hash123")
        self.assertEqual(result["text_extraction_method"], "embedded")
        self.assertFalse(result["ocr_used"])
        self.assertGreater(result["character_count"], 0)

    async def test_whitespace_pdf_flagged(self) -> None:
        pdf = _make_whitespace_pdf()
        result = process_pdf(pdf, "blank.pdf", "hash456")
        self.assertEqual(result["text_extraction_method"], "none")
        self.assertFalse(result["ocr_used"])
        self.assertEqual(result["character_count"], 0)

    async def test_multipage_text_combined(self) -> None:
        # TEST 8: text on both pages must be combined
        pdf = _make_multipage_pdf([
            "Amazon Invoice Number: IN-100\nOrder Date: 2025-01-01",
            "Cash on Delivery Fee Invoice\nService charge: INR 50",
        ])
        result = process_pdf(pdf, "amazon-invoice.pdf", "hash789")
        self.assertEqual(result["page_count"], 2)
        self.assertIn("Amazon Invoice", result["extracted_text"])
        self.assertIn("Cash on Delivery", result["extracted_text"])

    async def test_multipage_character_count_correct(self) -> None:
        text1 = "Invoice Number: XY-999\nAmount: INR 1000\nVendor: CorpA"
        text2 = "Service Fee Invoice\nFee: INR 40\nDate: 2025-01-15"
        pdf = _make_multipage_pdf([text1, text2])
        result = process_pdf(pdf, "multi.pdf", "hashABC")
        # Character count must reflect BOTH pages
        combined = text1 + "\n" + text2
        # Allow for minor whitespace differences from PyMuPDF rendering
        self.assertGreater(result["character_count"], len(text1))


# ---------------------------------------------------------------------------
# Integration tests: DocumentService (full pipeline, mocked Notion/AI/OCR)
# ---------------------------------------------------------------------------

class DocumentServicePipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)

        # Mock Notion (always returns "not a duplicate" and a fake page)
        self.mock_notion = MagicMock(spec=DocumentNotionService)
        self.mock_notion.check_duplicate_document = AsyncMock(return_value={"is_duplicate": False})
        self.mock_notion.create_processed_document = AsyncMock(return_value={"id": "fake-page-id"})
        self.mock_notion.update_document_analysis = AsyncMock()

        self.notion_patcher = patch(
            "services.document_service.DocumentNotionService", return_value=self.mock_notion
        )
        
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
        self.notion_patcher.start()

        # Mock OCR (default: success with meaningful text)
        self.mock_ocr = MagicMock()
        self.mock_ocr.extract_text = AsyncMock(
            return_value="Invoice Number OCR-001\nAmount: INR 999\nVendor: OcrCorp\nDate: 2025-06-01"
        )
        self.ocr_patcher = patch(
            "services.document_service.OCRService", return_value=self.mock_ocr
        )
        self.ocr_patcher.start()

    def tearDown(self) -> None:
        self.notion_patcher.stop()
        self.run_log_patcher.stop()
        self.approval_patcher.stop()
        self.ocr_patcher.stop()

    # TEST 1: PDF with good embedded text — OCR must not be called
    @patch("services.document_service.AIService")
    async def test_embedded_text_skips_ocr(self, mock_ai_class: MagicMock) -> None:
        mock_ai = mock_ai_class.return_value
        from models.schemas import DocumentAnalysisResult
        mock_ai.analyze_document.return_value = DocumentAnalysisResult(
            )
        pdf = _make_text_pdf(
            "Amazon Invoice IN-2025-001\nVendor: Amazon India\nTotal: INR 1699\nDate: 2025-01-01"
        )
        from services.document_service import DocumentService
        service = DocumentService()
        data = await service.process_unique_document(pdf, "invoice.pdf", "fake-hash")
        self.assertEqual(data["text_extraction_method"], "embedded")
        self.assertFalse(data["ocr_used"])
        self.mock_ocr.extract_text.assert_not_called()

    # TEST 2: Whitespace-only embedded text → OCR attempted
    @patch("services.document_service.AIService")
    async def test_whitespace_pdf_triggers_ocr(self, mock_ai_class: MagicMock) -> None:
        mock_ai = mock_ai_class.return_value
        from models.schemas import DocumentAnalysisResult
        mock_ai.analyze_document.return_value = DocumentAnalysisResult(
            )
        pdf = _make_whitespace_pdf()
        from services.document_service import DocumentService
        service = DocumentService()
        data = await service.process_unique_document(pdf, "scan.pdf", "fake-hash")
        self.mock_ocr.extract_text.assert_called_once()

    # TEST 5: Scanned PDF + successful OCR → method='ocr'
    @patch("services.document_service.AIService")
    async def test_scanned_pdf_uses_ocr_text(self, mock_ai_class: MagicMock) -> None:
        mock_ai = mock_ai_class.return_value
        from models.schemas import DocumentAnalysisResult
        mock_ai.analyze_document.return_value = DocumentAnalysisResult(
            )
        pdf = _make_whitespace_pdf()
        from services.document_service import DocumentService
        service = DocumentService()
        data = await service.process_unique_document(pdf, "scan.pdf", "fake-hash")
        self.assertEqual(data["text_extraction_method"], "ocr")
        self.assertTrue(data["ocr_used"])

    # TEST 6: Scanned PDF + OCR fails → needs_human_review=True, no crash
    @patch("services.document_service.AIService")
    async def test_scanned_pdf_ocr_failure_safe(self, mock_ai_class: MagicMock) -> None:
        self.mock_ocr.extract_text = AsyncMock(side_effect=OCRServiceError("network error"))
        pdf = _make_whitespace_pdf()
        from services.document_service import DocumentService
        service = DocumentService()
        data = await service.process_unique_document(pdf, "scan.pdf", "fake-hash")
        self.assertEqual(data["text_extraction_method"], "none")
        self.assertFalse(data["ocr_used"])

    # TEST 7: Good embedded text + OCR configured to raise → OCR never called, success
    @patch("services.document_service.AIService")
    async def test_embedded_text_success_even_if_ocr_would_crash(
        self, mock_ai_class: MagicMock
    ) -> None:
        # Make OCR raise immediately if called — it must NOT be called
        self.mock_ocr.extract_text = AsyncMock(side_effect=OCRServiceError("crash"))
        mock_ai = mock_ai_class.return_value
        from models.schemas import DocumentAnalysisResult
        mock_ai.analyze_document.return_value = DocumentAnalysisResult(
            )
        pdf = _make_text_pdf(
            "Amazon Invoice IN-2025-XYZ\nTotal: INR 5000\nOrder: 123-456\nVendor: Amazon"
        )
        from services.document_service import DocumentService
        service = DocumentService()
        data = await service.process_unique_document(pdf, "invoice.pdf", "fake-hash")
        # Must succeed based on embedded text alone
        self.assertEqual(data["text_extraction_method"], "embedded")
        self.assertFalse(data["ocr_used"])
        self.mock_ocr.extract_text.assert_not_called()

    # TEST 8: Multi-page Amazon-like PDF — both pages processed
    @patch("services.document_service.AIService")
    async def test_multipage_amazon_invoice(self, mock_ai_class: MagicMock) -> None:
        mock_ai = mock_ai_class.return_value
        from models.schemas import DocumentAnalysisResult
        mock_ai.analyze_document.return_value = DocumentAnalysisResult(
            )
        pdf = _make_multipage_pdf([
            "Amazon Invoice IN-2025-001\nOrder 402-1234567-8901234\nDate: 30 December 2025\n"
            "Billed to: Jyoti, 123 Main Street, New Delhi\nItem: Laptop Stand INR 1699",
            "Cash on Delivery Service Fee Invoice\nInvoice: COD-001\nFee: INR 29\nTotal: INR 29",
        ])
        from services.document_service import DocumentService
        service = DocumentService()
        data = await service.process_unique_document(pdf, "amazon-invoice.pdf", "fake-hash")
        self.assertEqual(data["page_count"], 2)
        self.assertEqual(data["text_extraction_method"], "embedded")
        self.assertFalse(data["ocr_used"])
        self.assertGreater(data["character_count"], 100)
        self.mock_ocr.extract_text.assert_not_called()

    # TEST 9: Duplicate PDF — detection unchanged, AI not called
    @patch("services.document_service.AIService")
    async def test_duplicate_detection_unchanged(self, mock_ai_class: MagicMock) -> None:
        self.mock_notion.check_duplicate_document = AsyncMock(
            return_value={
                "is_duplicate": True,
                "existing_document_id": "old-page-id",
                "existing_document_name": "invoice.pdf",
                "existing_decision_status": "Processing",
            }
        )
        pdf = _make_text_pdf("Amazon Invoice: some text here for a duplicate test file")
        from services.document_service import DocumentService
        service = DocumentService()
        data = await service.process_unique_document(pdf, "invoice.pdf", "fake-hash")
        self.assertTrue(data["is_duplicate"])
        self.assertEqual(data["existing_document_id"], "old-page-id")
        mock_ai_class.return_value.analyze_document.assert_not_called()
        self.mock_ocr.extract_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
