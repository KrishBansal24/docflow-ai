import logging
from typing import Any

import httpx

from config import get_settings
from models.workflow import ProcessingStatus, DecisionStatus
from models.approval import ApprovalDecision


logger = logging.getLogger(__name__)

NOTION_API_URL = "https://api.notion.com/v1"
# Current stable Notion API version at the time this project was created.
NOTION_API_VERSION = "2026-03-11"
FILE_HASH_PROPERTY = "File Hash"
DOCUMENT_NAME_PROPERTY = "Document Name"
PROCESSING_STATUS_PROPERTY = "Processing Status"
DECISION_STATUS_PROPERTY = "Decision Status"

# Approval Queue Properties
APPROVAL_NAME_PROPERTY = "Approval Name"
DOCUMENT_RELATION_PROPERTY = "Document"
APPROVAL_DECISION_PROPERTY = "Approval Decision"
REASON_PROPERTY = "Reason for Review"
REVIEWER_NOTES_PROPERTY = "Reviewer Notes"
CREATED_AT_PROPERTY = "Created At"
DECISION_DATE_PROPERTY = "Decision Date"


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
            PROCESSING_STATUS_PROPERTY: "status",
            DECISION_STATUS_PROPERTY: "status",
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
                + ". Add 'File Hash' as Rich Text, 'Document Name' as Title, and 'Processing Status' and 'Decision Status' as Status."
            )

        # Validate ProcessingStatus values
        available_processing_options = {
            option.get("name")
            for option in properties[PROCESSING_STATUS_PROPERTY].get("status", {}).get("options", [])
        }
        for status in ProcessingStatus:
            if status.value not in available_processing_options:
                logger.warning(
                    "[WORKFLOW] Notion Processing Status option '%s' not found in DOCUMENT INBOX. "
                    "It will be created automatically on first use.",
                    status.value,
                )

        # Validate DecisionStatus values
        available_decision_options = {
            option.get("name")
            for option in properties[DECISION_STATUS_PROPERTY].get("status", {}).get("options", [])
        }
        for status in DecisionStatus:
            if status.value not in available_decision_options:
                logger.warning(
                    "[WORKFLOW] Notion Decision Status option '%s' not found in DOCUMENT INBOX. "
                    "It will be created automatically on first use.",
                    status.value,
                )

    def _validate_approval_queue_schema(self, data_source: dict[str, Any]) -> None:
        """Ensure the APPROVAL QUEUE has required properties and statuses."""
        properties = data_source.get("properties", {})
        required_types = {
            APPROVAL_NAME_PROPERTY: "title",
            DOCUMENT_RELATION_PROPERTY: "relation",
            APPROVAL_DECISION_PROPERTY: "status",
        }
        missing_or_invalid = [
            f"{name} ({property_type})"
            for name, property_type in required_types.items()
            if properties.get(name, {}).get("type") != property_type
        ]
        if missing_or_invalid:
            raise NotionServiceError(
                "APPROVAL QUEUE is missing required properties: "
                + ", ".join(missing_or_invalid)
            )

        available_options = {
            option.get("name")
            for option in properties[APPROVAL_DECISION_PROPERTY].get("status", {}).get("options", [])
        }
        for decision in ApprovalDecision:
            if decision.value not in available_options:
                logger.warning(
                    "[WORKFLOW] Notion Approval Decision option '%s' not found in APPROVAL QUEUE. "
                    "It will be created automatically on first use.",
                    decision.value,
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
        processing_status_value = properties.get(PROCESSING_STATUS_PROPERTY, {}).get("status")
        decision_status_value = properties.get(DECISION_STATUS_PROPERTY, {}).get("status")
        return {
            "is_duplicate": True,
            "existing_document_id": existing_page.get("id"),
            "existing_document_name": self._read_plain_text(
                properties.get(DOCUMENT_NAME_PROPERTY, {}), "title"
            ),
            "existing_document_status": (
                processing_status_value.get("name") if isinstance(processing_status_value, dict) else None
            ),
            "existing_decision_status": (
                decision_status_value.get("name") if isinstance(decision_status_value, dict) else None
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
                PROCESSING_STATUS_PROPERTY: {"status": {"name": ProcessingStatus.PROCESSING.value}},
                DECISION_STATUS_PROPERTY: {"status": {"name": DecisionStatus.PENDING_DECISION.value}},
            },
        }
        return await self._request("POST", "/pages", json=payload)

    async def update_document_analysis(self, page_id: str, analysis_result: Any | None, processing_status_name: str) -> dict[str, Any]:
        """Update an existing Notion page with AI analysis results safely."""
        document_source = await self._get_data_source(self.settings.document_inbox_id or "")
        properties_schema = document_source.get("properties", {})
        
        properties_payload: dict[str, Any] = {}
        
        # Always update processing status if possible
        if PROCESSING_STATUS_PROPERTY in properties_schema:
            properties_payload[PROCESSING_STATUS_PROPERTY] = {"status": {"name": processing_status_name}}
            
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
                
        if not properties_payload:
            return {}
            
        payload = {"properties": properties_payload}
        return await self._request("PATCH", f"/pages/{page_id}", json=payload)

    async def update_decision_status_only(self, page_id: str, decision_status_name: str) -> dict[str, Any]:
        """Update just the decision status of a DOCUMENT INBOX page."""
        payload = {
            "properties": {
                DECISION_STATUS_PROPERTY: {"status": {"name": decision_status_name}}
            }
        }
        return await self._request("PATCH", f"/pages/{page_id}", json=payload)

    async def check_existing_approval(self, document_id: str) -> dict[str, Any] | None:
        """Check if an approval entry already exists for a document."""
        if not self.settings.approval_queue_id:
            raise NotionServiceError("APPROVAL_QUEUE_ID is not configured.")
            
        approval_source = await self._get_data_source(self.settings.approval_queue_id)
        self._validate_approval_queue_schema(approval_source)
        
        response = await self._request(
            "POST",
            f"/data_sources/{approval_source['id']}/query",
            json={
                "page_size": 1,
                "filter": {
                    "property": DOCUMENT_RELATION_PROPERTY,
                    "relation": {"contains": document_id},
                },
            },
        )
        
        results = response.get("results")
        if not results:
            return None
            
        page = results[0]
        properties = page.get("properties", {})
        decision_value = properties.get(APPROVAL_DECISION_PROPERTY, {}).get("status")
        
        return {
            "id": page.get("id"),
            "status": decision_value.get("name") if isinstance(decision_value, dict) else None,
        }

    async def create_approval_entry(self, document_id: str, document_name: str, reason: str, created_at: str) -> dict[str, Any]:
        """Create a new pending approval entry."""
        if not self.settings.approval_queue_id:
            raise NotionServiceError("APPROVAL_QUEUE_ID is not configured.")
            
        approval_source = await self._get_data_source(self.settings.approval_queue_id)
        self._validate_approval_queue_schema(approval_source)
        
        properties_payload: dict[str, Any] = {
            APPROVAL_NAME_PROPERTY: {
                "title": [{"text": {"content": f"Approval: {document_name}"}}],
            },
            DOCUMENT_RELATION_PROPERTY: {
                "relation": [{"id": document_id}],
            },
            APPROVAL_DECISION_PROPERTY: {
                "status": {"name": ApprovalDecision.PENDING_DECISION.value},
            },
        }
        
        schema = approval_source.get("properties", {})
        if REASON_PROPERTY in schema and schema[REASON_PROPERTY].get("type") == "rich_text":
            properties_payload[REASON_PROPERTY] = {"rich_text": [{"text": {"content": reason}}]}
            
        if CREATED_AT_PROPERTY in schema and schema[CREATED_AT_PROPERTY].get("type") == "date":
            properties_payload[CREATED_AT_PROPERTY] = {"date": {"start": created_at}}
            
        payload = {
            "parent": {"type": "data_source_id", "data_source_id": approval_source["id"]},
            "properties": properties_payload,
        }
        return await self._request("POST", "/pages", json=payload)

    async def get_pending_approvals(self) -> list[dict[str, Any]]:
        """Get all pending approval items."""
        if not self.settings.approval_queue_id:
            raise NotionServiceError("APPROVAL_QUEUE_ID is not configured.")
            
        approval_source = await self._get_data_source(self.settings.approval_queue_id)
        self._validate_approval_queue_schema(approval_source)
        
        response = await self._request(
            "POST",
            f"/data_sources/{approval_source['id']}/query",
            json={
                "filter": {
                    "property": APPROVAL_DECISION_PROPERTY,
                    "status": {"equals": ApprovalDecision.PENDING_DECISION.value},
                },
            },
        )
        
        return response.get("results", [])

    async def get_approval_entry(self, approval_id: str) -> dict[str, Any]:
        """Get a specific approval entry by ID."""
        return await self._request("GET", f"/pages/{approval_id}")

    async def update_approval_decision(self, approval_id: str, decision: str, notes: str | None, decision_date: str) -> dict[str, Any]:
        """Update an approval entry with a decision."""
        if not self.settings.approval_queue_id:
            raise NotionServiceError("APPROVAL_QUEUE_ID is not configured.")
            
        approval_source = await self._get_data_source(self.settings.approval_queue_id)
        schema = approval_source.get("properties", {})
        
        properties_payload: dict[str, Any] = {
            APPROVAL_DECISION_PROPERTY: {"status": {"name": decision}}
        }
        
        if notes and REVIEWER_NOTES_PROPERTY in schema and schema[REVIEWER_NOTES_PROPERTY].get("type") == "rich_text":
            properties_payload[REVIEWER_NOTES_PROPERTY] = {"rich_text": [{"text": {"content": notes}}]}
            
        if DECISION_DATE_PROPERTY in schema and schema[DECISION_DATE_PROPERTY].get("type") == "date":
            properties_payload[DECISION_DATE_PROPERTY] = {"date": {"start": decision_date}}
            
        payload = {"properties": properties_payload}
        return await self._request("PATCH", f"/pages/{approval_id}", json=payload)

