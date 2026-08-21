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


class DocumentUploadResponse(BaseModel):
    filename: str
    page_count: int
    text: str
    character_count: int
    file_hash: str
    needs_human_review: bool
    message: str
