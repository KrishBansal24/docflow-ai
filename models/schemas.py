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


class DuplicateDocumentResponse(BaseModel):
    is_duplicate: Literal[True]
    message: str
    existing_document_id: str
    file_hash: str
    existing_document_name: str | None = None
    existing_document_status: str | None = None
