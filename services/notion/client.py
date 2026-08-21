import logging
from typing import Any

import httpx

from config import get_settings


logger = logging.getLogger(__name__)

NOTION_API_URL = "https://api.notion.com/v1"
NOTION_API_VERSION = "2026-03-11"

class NotionServiceError(Exception):
    """A clear, safe error returned when a Notion API request cannot complete."""


class NotionClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        missing_values = self.settings.missing_notion_values()
        if missing_values:
            raise NotionServiceError(
                "Missing required environment variables: " + ", ".join(missing_values)
            )

        self.headers = {
            "Authorization": f"Bearer {self.settings.notion_token}",
            "Notion-Version": NOTION_API_VERSION,
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.request(
                    method,
                    f"{NOTION_API_URL}{path}",
                    headers=self.headers,
                    **kwargs,
                )
        except httpx.RequestError as exc:
            raise NotionServiceError("Could not reach the Notion API. Check your internet connection.") from exc

        if response.is_error:
            try:
                error_message = response.json().get("message", response.text)
            except ValueError:
                error_message = response.text
            raise NotionServiceError(
                f"Notion API error ({response.status_code}): {error_message}"
            )

        return response.json()

    async def _get_data_source(self, configured_id: str) -> dict[str, Any]:
        """Resolve a database ID from a Notion URL to its first data source."""
        database_response = await self._request("GET", f"/databases/{configured_id}")
        data_sources = database_response.get("data_sources", [])
        if len(data_sources) == 1:
            return await self._request("GET", f"/data_sources/{data_sources[0]['id']}")
        if len(data_sources) > 1:
            raise NotionServiceError(
                "This database has multiple data sources. Set its environment value to the specific data source ID."
            )

        return await self._request("GET", f"/data_sources/{configured_id}")

    async def test_connection(self) -> dict[str, str]:
        configured_databases = {
            "DOCUMENT INBOX": self.settings.document_inbox_id,
            "APPROVAL QUEUE": self.settings.approval_queue_id,
            "RUN LOG": self.settings.run_log_id,
        }
        verified: dict[str, str] = {}
        for display_name, configured_id in configured_databases.items():
            data_source = await self._get_data_source(configured_id or "")
            verified[display_name] = data_source["id"]
        return verified

    @staticmethod
    def _read_plain_text(property_value: dict[str, Any], value_type: str) -> str | None:
        """Return a human-readable Notion title or rich-text value, if present."""
        fragments = property_value.get(value_type, [])
        if not isinstance(fragments, list):
            return None
        text = "".join(fragment.get("plain_text", "") for fragment in fragments)
        return text or None
