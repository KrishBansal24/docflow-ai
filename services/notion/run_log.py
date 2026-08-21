import logging
from typing import Any

from services.notion.client import NotionClient, NotionServiceError

logger = logging.getLogger(__name__)


class RunLogNotionService:
    def __init__(self, client: NotionClient | None = None) -> None:
        self.client = client or NotionClient()

    async def create_run_log_entry(self, event: str, status: str, details: str, document_id: str | None = None) -> dict[str, Any]:
        """Create a new timestamped row in the Run Log database."""
        if not self.client.settings.run_log_id:
            logger.warning("[RUN LOG] RUN_LOG_ID is not configured. Skipping run log entry.")
            return {}

        properties: dict[str, Any] = {
            "Event": {"title": [{"text": {"content": event}}]},
            "Status": {"select": {"name": status}},
            "Details": {"rich_text": [{"text": {"content": details}}]},
        }
        
        if document_id:
            properties["Document"] = {"relation": [{"id": document_id}]}

        payload = {
            "parent": {"database_id": self.client.settings.run_log_id},
            "properties": properties
        }
        
        try:
            return await self.client._request("POST", "/pages", json=payload)
        except NotionServiceError as exc:
            logger.error("[RUN LOG] Failed to write to run log: %s", exc)
            return {}
