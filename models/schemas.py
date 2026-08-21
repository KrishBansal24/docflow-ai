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
