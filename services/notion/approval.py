import logging
from typing import Any

from models.approval import ApprovalDecision
from services.notion.client import NotionClient, NotionServiceError

logger = logging.getLogger(__name__)

APPROVAL_NAME_PROPERTY = "Approval Name"
DOCUMENT_RELATION_PROPERTY = "Document"
APPROVAL_DECISION_PROPERTY = "Approval Decision"
REASON_PROPERTY = "Reason for Review"
REVIEWER_NOTES_PROPERTY = "Reviewer Notes"
CREATED_AT_PROPERTY = "Created At"
DECISION_DATE_PROPERTY = "Decision Date"
PRIORITY_PROPERTY = "Priority"


class ApprovalNotionService:
    def __init__(self, client: NotionClient | None = None) -> None:
        self.client = client or NotionClient()

    def _validate_schema(self, data_source: dict[str, Any]) -> None:
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

    async def check_existing_approval(self, document_id: str) -> dict[str, Any] | None:
        if not self.client.settings.approval_queue_id:
            raise NotionServiceError("APPROVAL_QUEUE_ID is not configured.")
            
        approval_source = await self.client._get_data_source(self.client.settings.approval_queue_id)
        self._validate_schema(approval_source)
        
        response = await self.client._request(
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

    async def create_approval_entry(
        self, document_id: str, document_name: str, reason: str, created_at: str, priority: str | None = None
    ) -> dict[str, Any]:
        if not self.client.settings.approval_queue_id:
            raise NotionServiceError("APPROVAL_QUEUE_ID is not configured.")
            
        approval_source = await self.client._get_data_source(self.client.settings.approval_queue_id)
        self._validate_schema(approval_source)
        
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
            
        if priority and PRIORITY_PROPERTY in schema and schema[PRIORITY_PROPERTY].get("type") == "select":
            properties_payload[PRIORITY_PROPERTY] = {"select": {"name": priority}}
            
        payload = {
            "parent": {"type": "data_source_id", "data_source_id": approval_source["id"]},
            "properties": properties_payload,
        }
        return await self.client._request("POST", "/pages", json=payload)

    async def get_pending_approvals(self) -> list[dict[str, Any]]:
        if not self.client.settings.approval_queue_id:
            raise NotionServiceError("APPROVAL_QUEUE_ID is not configured.")
            
        approval_source = await self.client._get_data_source(self.client.settings.approval_queue_id)
        self._validate_schema(approval_source)
        
        response = await self.client._request(
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
        return await self.client._request("GET", f"/pages/{approval_id}")

    async def update_approval_decision(self, approval_id: str, decision: str, notes: str | None, decision_date: str) -> dict[str, Any]:
        if not self.client.settings.approval_queue_id:
            raise NotionServiceError("APPROVAL_QUEUE_ID is not configured.")
            
        approval_source = await self.client._get_data_source(self.client.settings.approval_queue_id)
        schema = approval_source.get("properties", {})
        
        properties_payload: dict[str, Any] = {
            APPROVAL_DECISION_PROPERTY: {"status": {"name": decision}}
        }
        
        if notes and REVIEWER_NOTES_PROPERTY in schema and schema[REVIEWER_NOTES_PROPERTY].get("type") == "rich_text":
            properties_payload[REVIEWER_NOTES_PROPERTY] = {"rich_text": [{"text": {"content": notes}}]}
            
        if DECISION_DATE_PROPERTY in schema and schema[DECISION_DATE_PROPERTY].get("type") == "date":
            properties_payload[DECISION_DATE_PROPERTY] = {"date": {"start": decision_date}}
            
        payload = {"properties": properties_payload}
        return await self.client._request("PATCH", f"/pages/{approval_id}", json=payload)
