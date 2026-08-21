import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel


load_dotenv()


class Settings(BaseModel):
    """Configuration loaded from environment variables, never source code."""

    notion_token: str | None = os.getenv("NOTION_TOKEN")
    document_inbox_id: str | None = os.getenv("DOCUMENT_INBOX_ID")
    approval_queue_id: str | None = os.getenv("APPROVAL_QUEUE_ID")
    run_log_id: str | None = os.getenv("RUN_LOG_ID")

    def missing_notion_values(self) -> list[str]:
        values = {
            "NOTION_TOKEN": self.notion_token,
            "DOCUMENT_INBOX_ID": self.document_inbox_id,
            "APPROVAL_QUEUE_ID": self.approval_queue_id,
            "RUN_LOG_ID": self.run_log_id,
        }
        return [name for name, value in values.items() if not value]


@lru_cache
def get_settings() -> Settings:
    return Settings()
