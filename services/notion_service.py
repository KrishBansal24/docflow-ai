from typing import Any

import httpx

from config import get_settings


NOTION_API_URL = "https://api.notion.com/v1"
# Current stable Notion API version at the time this project was created.
NOTION_API_VERSION = "2026-03-11"
FILE_HASH_PROPERTY = "File Hash"
DOCUMENT_NAME_PROPERTY = "Document Name"
STATUS_PROPERTY = "Status"
INITIAL_DOCUMENT_STATUS = "Processing"


class NotionServiceError(Exception):
    """A clear, safe error returned when a Notion API request cannot complete."""


class NotionService:
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
        """Resolve a database ID from a Notion URL to its first data source.

        Notion's current API writes rows to data sources. Supplying a data source ID
        directly also works, which is useful for databases with multiple sources.
        """
        database_response = await self._request("GET", f"/databases/{configured_id}")
        data_sources = database_response.get("data_sources", [])
        if len(data_sources) == 1:
            return await self._request("GET", f"/data_sources/{data_sources[0]['id']}")
        if len(data_sources) > 1:
            raise NotionServiceError(
                "This database has multiple data sources. Set its environment value to the specific data source ID."
            )

        # This permits an advanced user to provide a data source ID directly.
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

    async def create_test_document(self) -> dict[str, Any]:
        document_source = await self._get_data_source(self.settings.document_inbox_id or "")
        title_property = next(
            (
                name
                for name, property_definition in document_source.get("properties", {}).items()
                if property_definition.get("type") == "title"
            ),
            None,
        )
        if not title_property:
            raise NotionServiceError(
                "DOCUMENT INBOX needs a Title property before a test document can be created."
            )

        payload = {
            "parent": {"type": "data_source_id", "data_source_id": document_source["id"]},
            "properties": {
                title_property: {
                    "title": [{"text": {"content": "DocFlow AI - Test Document"}}]
                }
            },
        }
        return await self._request("POST", "/pages", json=payload)

    @staticmethod
    def _read_plain_text(property_value: dict[str, Any], value_type: str) -> str | None:
        """Return a human-readable Notion title or rich-text value, if present."""
        fragments = property_value.get(value_type, [])
        if not isinstance(fragments, list):
            return None
        text = "".join(fragment.get("plain_text", "") for fragment in fragments)
        return text or None

    def _validate_document_inbox_schema(self, data_source: dict[str, Any]) -> None:
        """Ensure Phase 3 relies only on verified, compatible Notion properties."""
        properties = data_source.get("properties", {})
        required_types = {
            FILE_HASH_PROPERTY: "rich_text",
            DOCUMENT_NAME_PROPERTY: "title",
            STATUS_PROPERTY: "status",
        }
        missing_or_invalid = [
            f"{name} ({property_type})"
            for name, property_type in required_types.items()
            if properties.get(name, {}).get("type") != property_type
        ]
        if missing_or_invalid:
            raise NotionServiceError(
                "DOCUMENT INBOX is missing required Phase 3 properties: "
                + ", ".join(missing_or_invalid)
                + ". Add 'File Hash' as Rich Text, 'Document Name' as Title, and 'Status' as Status."
            )

        status_options = properties[STATUS_PROPERTY].get("status", {}).get("options", [])
        if INITIAL_DOCUMENT_STATUS not in {option.get("name") for option in status_options}:
            raise NotionServiceError(
                f"DOCUMENT INBOX Status needs an '{INITIAL_DOCUMENT_STATUS}' option for Phase 3."
            )

    async def check_duplicate_document(self, file_hash: str) -> dict[str, Any]:
        """Find a Document Inbox page with an exactly matching SHA-256 hash."""
        document_source = await self._get_data_source(self.settings.document_inbox_id or "")
        self._validate_document_inbox_schema(document_source)
        response = await self._request(
            "POST",
            f"/data_sources/{document_source['id']}/query",
            json={
                "page_size": 1,
                "filter": {
                    "property": FILE_HASH_PROPERTY,
                    "rich_text": {"equals": file_hash},
                },
            },
        )
        results = response.get("results")
        if not isinstance(results, list):
            raise NotionServiceError("Notion returned an unexpected duplicate-check response.")
        if not results:
            return {"is_duplicate": False}

        existing_page = results[0]
        properties = existing_page.get("properties", {})
        status_value = properties.get(STATUS_PROPERTY, {}).get("status")
        return {
            "is_duplicate": True,
            "existing_document_id": existing_page.get("id"),
            "existing_document_name": self._read_plain_text(
                properties.get(DOCUMENT_NAME_PROPERTY, {}), "title"
            ),
            "existing_document_status": (
                status_value.get("name") if isinstance(status_value, dict) else None
            ),
        }

    async def create_processed_document(self, filename: str, file_hash: str) -> dict[str, Any]:
        """Create the one Document Inbox record used for future hash lookups."""
        document_source = await self._get_data_source(self.settings.document_inbox_id or "")
        self._validate_document_inbox_schema(document_source)
        payload = {
            "parent": {"type": "data_source_id", "data_source_id": document_source["id"]},
            "properties": {
                DOCUMENT_NAME_PROPERTY: {
                    "title": [{"text": {"content": filename}}],
                },
                FILE_HASH_PROPERTY: {
                    "rich_text": [{"text": {"content": file_hash}}],
                },
                STATUS_PROPERTY: {"status": {"name": INITIAL_DOCUMENT_STATUS}},
            },
        }
        return await self._request("POST", "/pages", json=payload)
