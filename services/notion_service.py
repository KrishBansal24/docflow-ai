import logging
from typing import Any

import httpx

from config import get_settings
from models.workflow import DocumentStatus


logger = logging.getLogger(__name__)

NOTION_API_URL = "https://api.notion.com/v1"
# Current stable Notion API version at the time this project was created.
NOTION_API_VERSION = "2026-03-11"
FILE_HASH_PROPERTY = "File Hash"
DOCUMENT_NAME_PROPERTY = "Document Name"
STATUS_PROPERTY = "Status"


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
        """Ensure the DOCUMENT INBOX has required properties and workflow statuses."""
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
                "DOCUMENT INBOX is missing required properties: "
                + ", ".join(missing_or_invalid)
                + ". Add 'File Hash' as Rich Text, 'Document Name' as Title, and 'Status' as Status."
            )

        # Validate that all DocumentStatus values exist as Status options.
        # Missing options are logged as warnings but do NOT crash — Notion
        # auto-creates status options when written for the first time.
        available_options = {
            option.get("name")
            for option in properties[STATUS_PROPERTY].get("status", {}).get("options", [])
        }
        for status in DocumentStatus:
            if status.value not in available_options:
                logger.warning(
                    "[WORKFLOW] Notion Status option '%s' not found in DOCUMENT INBOX. "
                    "It will be created automatically on first use.",
                    status.value,
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
                STATUS_PROPERTY: {"status": {"name": DocumentStatus.PROCESSING.value}},
            },
        }
        return await self._request("POST", "/pages", json=payload)

    async def update_document_analysis(self, page_id: str, analysis_result: Any | None, status_name: str) -> dict[str, Any]:
        """Update an existing Notion page with AI analysis results safely."""
        document_source = await self._get_data_source(self.settings.document_inbox_id or "")
        properties_schema = document_source.get("properties", {})
        
        properties_payload: dict[str, Any] = {}
        
        # Always update status if possible
        if STATUS_PROPERTY in properties_schema:
            properties_payload[STATUS_PROPERTY] = {"status": {"name": status_name}}
            
        if analysis_result:
            if "Document Type" in properties_schema and properties_schema["Document Type"].get("type") == "select" and analysis_result.document_type:
                properties_payload["Document Type"] = {"select": {"name": analysis_result.document_type}}
            
            if "Vendor" in properties_schema and properties_schema["Vendor"].get("type") == "rich_text" and analysis_result.vendor_or_company:
                properties_payload["Vendor"] = {"rich_text": [{"text": {"content": analysis_result.vendor_or_company}}]}
                
            if "Reference Number" in properties_schema and properties_schema["Reference Number"].get("type") == "rich_text" and analysis_result.reference_number:
                properties_payload["Reference Number"] = {"rich_text": [{"text": {"content": analysis_result.reference_number}}]}
                
            if "Amount" in properties_schema and properties_schema["Amount"].get("type") == "number" and analysis_result.amount is not None:
                properties_payload["Amount"] = {"number": analysis_result.amount}
                
            if "Currency" in properties_schema and properties_schema["Currency"].get("type") == "select" and analysis_result.currency:
                properties_payload["Currency"] = {"select": {"name": analysis_result.currency}}
                
            if "Due Date" in properties_schema and properties_schema["Due Date"].get("type") == "date" and analysis_result.due_date:
                properties_payload["Due Date"] = {"date": {"start": analysis_result.due_date}}
                
            if "Priority" in properties_schema and properties_schema["Priority"].get("type") == "select" and analysis_result.priority:
                properties_payload["Priority"] = {"select": {"name": analysis_result.priority}}
                
            if "AI Summary" in properties_schema and properties_schema["AI Summary"].get("type") == "rich_text" and analysis_result.short_summary:
                properties_payload["AI Summary"] = {"rich_text": [{"text": {"content": analysis_result.short_summary}}]}
                
            if "Required Action" in properties_schema and properties_schema["Required Action"].get("type") == "rich_text" and analysis_result.required_action:
                properties_payload["Required Action"] = {"rich_text": [{"text": {"content": analysis_result.required_action}}]}
                
            if "Suggested Recipient" in properties_schema and properties_schema["Suggested Recipient"].get("type") == "rich_text" and analysis_result.suggested_recipient:
                properties_payload["Suggested Recipient"] = {"rich_text": [{"text": {"content": analysis_result.suggested_recipient}}]}
                
            if "AI Confidence" in properties_schema and properties_schema["AI Confidence"].get("type") == "number" and analysis_result.confidence is not None:
                properties_payload["AI Confidence"] = {"number": analysis_result.confidence}
                
            if "Human Approval Required" in properties_schema and properties_schema["Human Approval Required"].get("type") == "checkbox" and analysis_result.requires_human_approval is not None:
                properties_payload["Human Approval Required"] = {"checkbox": analysis_result.requires_human_approval}
                
        if not properties_payload:
            return {}
            
        payload = {"properties": properties_payload}
        return await self._request("PATCH", f"/pages/{page_id}", json=payload)

