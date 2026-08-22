import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, Field


load_dotenv()


class Settings(BaseModel):
    """Configuration loaded from environment variables, never source code."""

    notion_token: str | None = os.getenv("NOTION_TOKEN")
    document_inbox_id: str | None = os.getenv("DOCUMENT_INBOX_ID")
    approval_queue_id: str | None = os.getenv("APPROVAL_QUEUE_ID")
    run_log_id: str | None = os.getenv("RUN_LOG_ID")
    
    # SMTP Settings
    smtp_host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str | None = os.getenv("SMTP_USERNAME")
    smtp_password: str | None = os.getenv("SMTP_PASSWORD")
    smtp_from_email: str | None = os.getenv("SMTP_FROM_EMAIL", smtp_username)
    max_upload_size_mb: int = Field(
        default_factory=lambda: int(os.getenv("MAX_UPLOAD_SIZE_MB", "10")),
        ge=1,
    )
    
    # Department Emails
    email_finance: str | None = os.getenv("EMAIL_FINANCE")
    email_it: str | None = os.getenv("EMAIL_IT")
    email_legal: str | None = os.getenv("EMAIL_LEGAL")
    email_hr: str | None = os.getenv("EMAIL_HR")
    email_operations: str | None = os.getenv("EMAIL_OPERATIONS")
    email_default: str | None = os.getenv("EMAIL_DEFAULT", smtp_from_email)
    
    # Phase 4 AI Settings
    ai_provider: str = os.getenv("AI_PROVIDER", "gemini")
    ai_api_key: str | None = os.getenv("AI_API_KEY")
    ai_model: str = os.getenv("AI_MODEL", "gemini-3.6-flash")
    
    # OCR Fallback Settings
    mistral_api_key: str | None = os.getenv("MISTRAL_API_KEY")
    
    # Text quality thresholds for deciding if embedded text is meaningful
    min_embedded_text_length: int = Field(
        default_factory=lambda: int(os.getenv("MIN_EMBEDDED_TEXT_LENGTH", "50")),
        ge=0,
    )
    min_text_alphanumeric_ratio: float = Field(
        default_factory=lambda: float(os.getenv("MIN_TEXT_ALPHANUMERIC_RATIO", "0.30")),
        ge=0.0,
        le=1.0,
    )

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    def missing_notion_values(self) -> list[str]:
        values = {
            "NOTION_TOKEN": self.notion_token,
            "DOCUMENT_INBOX_ID": self.document_inbox_id,
            "APPROVAL_QUEUE_ID": self.approval_queue_id,
            "RUN_LOG_ID": self.run_log_id,
        }
        return [name for name, value in values.items() if not value]
        
    def missing_ai_values(self) -> list[str]:
        values = {
            "AI_API_KEY": self.ai_api_key,
        }
        return [name for name, value in values.items() if not value]


@lru_cache
def get_settings() -> Settings:
    return Settings()
