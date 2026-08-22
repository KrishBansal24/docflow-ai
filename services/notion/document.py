import logging
from typing import Any

from models.workflow import ProcessingStatus, DecisionStatus
from models.schemas import DocumentAnalysisResult
from services.notion.client import NotionClient, NotionServiceError

logger = logging.getLogger(__name__)

FILE_HASH_PROPERTY = "File Hash"
DOCUMENT_NAME_PROPERTY = "Document Name"
PROCESSING_STATUS_PROPERTY = "Processing Status"
DECISION_STATUS_PROPERTY = "Decision Status"


class DocumentNotionService:
    def __init__(self, client: NotionClient | None = None) -> None:
        self.client = client or NotionClient()

    def _validate_schema(self, data_source: dict[str, Any]) -> None:
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

    async def create_test_document(self) -> dict[str, Any]:
        document_source = await self.client._get_data_source(self.client.settings.document_inbox_id or "")
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
        return await self.client._request("POST", "/pages", json=payload)

    async def check_duplicate_document(self, file_hash: str) -> dict[str, Any]:
        document_source = await self.client._get_data_source(self.client.settings.document_inbox_id or "")
        self._validate_schema(document_source)
        response = await self.client._request(
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
            "existing_document_name": NotionClient._read_plain_text(
                properties.get(DOCUMENT_NAME_PROPERTY, {}), "title"
            ),
            "existing_document_status": (
                processing_status_value.get("name") if isinstance(processing_status_value, dict) else None
            ),
            "existing_decision_status": (
                decision_status_value.get("name") if isinstance(decision_status_value, dict) else None
            ),
        }

    async def get_document(self, document_id: str) -> dict[str, Any]:
        return await self.client._request("GET", f"/pages/{document_id}")

    async def create_processed_document(self, filename: str, file_hash: str) -> dict[str, Any]:
        document_source = await self.client._get_data_source(self.client.settings.document_inbox_id or "")
        self._validate_schema(document_source)
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
        return await self.client._request("POST", "/pages", json=payload)

    async def update_document_properties(
        self,
        document_id: str,
        processing_status_name: str,
        analysis_result: DocumentAnalysisResult | None = None,
        custom_title: str | None = None,
    ) -> dict[str, Any]:
        document_source = await self.client._get_data_source(self.client.settings.document_inbox_id or "")
        properties_schema = document_source.get("properties", {})
        
        properties_payload: dict[str, Any] = {}
        
        if PROCESSING_STATUS_PROPERTY in properties_schema:
            properties_payload[PROCESSING_STATUS_PROPERTY] = {"status": {"name": processing_status_name}}
            
        if custom_title:
            title_property = next(
                (
                    name
                    for name, prop in properties_schema.items()
                    if prop.get("type") == "title"
                ),
                None,
            )
            if title_property:
                properties_payload[title_property] = {"title": [{"text": {"content": custom_title}}]}
            
        if analysis_result:
            if "Document Type" in properties_schema and properties_schema["Document Type"].get("type") == "select" and analysis_result.document_type:
                properties_payload["Document Type"] = {"select": {"name": analysis_result.document_type}}
                
            if "Department" in properties_schema and properties_schema["Department"].get("type") == "multi_select" and analysis_result.departments:
                properties_payload["Department"] = {"multi_select": [{"name": dep} for dep in analysis_result.departments if dep]}
            elif "Departments" in properties_schema and properties_schema["Departments"].get("type") == "multi_select" and analysis_result.departments:
                properties_payload["Departments"] = {"multi_select": [{"name": dep} for dep in analysis_result.departments if dep]}
            
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
        return await self.client._request("PATCH", f"/pages/{document_id}", json=payload)

    async def update_decision_status_only(self, page_id: str, decision_status_name: str) -> dict[str, Any]:
        payload = {
            "properties": {
                DECISION_STATUS_PROPERTY: {"status": {"name": decision_status_name}}
            }
        }
        return await self.client._request("PATCH", f"/pages/{page_id}", json=payload)
