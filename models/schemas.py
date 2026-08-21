from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str


class NotionTestResponse(BaseModel):
    success: bool
    message: str
    databases: dict[str, str]


class TestDocumentResponse(BaseModel):
    success: bool
    message: str
    page_id: str
    page_url: str | None = None


class DocumentAnalysisResult(BaseModel):
    document_type: str | None = None
    vendor_or_company: str | None = None
    reference_number: str | None = None
    amount: float | None = None
    currency: str | None = None
    due_date: str | None = None
    priority: str | None = None
    short_summary: str | None = None
    required_action: str | None = None
    suggested_recipient: str | None = None
    confidence: float
    requires_human_approval: bool
    reasoning_summary: str | None = None


class UniqueDocumentResponse(BaseModel):
    is_duplicate: Literal[False]
    message: str
    document_id: str
    filename: str
    page_count: int
    text: str
    character_count: int
    file_hash: str
    needs_human_review: bool
    text_extraction_method: str  # 'embedded', 'ocr', or 'none'
    ocr_used: bool
    analysis: DocumentAnalysisResult | None = None


class DuplicateDocumentResponse(BaseModel):
    is_duplicate: Literal[True]
    message: str
    existing_document_id: str
    file_hash: str
    existing_document_name: str | None = None
    existing_document_status: str | None = None
