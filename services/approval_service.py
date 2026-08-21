import logging
from datetime import datetime, timezone

from models.approval import ApprovalStatus
from models.workflow import DocumentStatus
from services.notion_service import NotionService, NotionServiceError

logger = logging.getLogger(__name__)


class ApprovalServiceError(Exception):
    """Raised when an approval queue operation fails."""
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


class ApprovalService:
    def __init__(self) -> None:
        self.notion_service = NotionService()

    async def queue_document_for_review(self, document_id: str, document_name: str, reason: str) -> dict[str, str]:
        """Create a new approval entry if one doesn't exist."""
        try:
            existing = await self.notion_service.check_existing_approval(document_id)
            if existing:
                logger.info("[APPROVAL] Existing approval entry found for %s (id=%s)", document_id, existing["id"])
                return existing

            logger.info("[APPROVAL] Document requires human review: %s. Creating queue entry.", document_name)
            now_iso = datetime.now(timezone.utc).isoformat()
            
            new_approval = await self.notion_service.create_approval_entry(
                document_id=document_id,
                document_name=document_name,
                reason=reason,
                created_at=now_iso,
            )
            logger.info("[APPROVAL] Approval queue entry created: %s", new_approval["id"])
            return {"id": new_approval["id"], "status": ApprovalStatus.PENDING_APPROVAL.value}

        except NotionServiceError as exc:
            logger.error("[APPROVAL] Failed to queue document %s: %s", document_name, exc)
            # We raise so the caller knows the queue failed, though we may handle it gracefully upstream.
            raise ApprovalServiceError(f"Could not queue document for approval: {exc}") from exc

    async def get_pending_approvals(self) -> list[dict]:
        """Retrieve all pending approvals."""
        try:
            results = await self.notion_service.get_pending_approvals()
            approvals = []
            for page in results:
                props = page.get("properties", {})
                
                # Extract related document ID
                doc_relation = props.get("Document", {}).get("relation", [])
                doc_id = doc_relation[0]["id"] if doc_relation else ""
                
                # Extract simple text fields
                def _get_text(prop_name: str) -> str | None:
                    rich_text = props.get(prop_name, {}).get("rich_text", [])
                    return "".join(t.get("plain_text", "") for t in rich_text) if rich_text else None
                    
                def _get_title(prop_name: str) -> str | None:
                    title = props.get(prop_name, {}).get("title", [])
                    return "".join(t.get("plain_text", "") for t in title) if title else None
                
                def _get_date(prop_name: str) -> str | None:
                    date_obj = props.get(prop_name, {}).get("date")
                    return date_obj.get("start") if date_obj else None
                
                status_obj = props.get("Approval Status", {}).get("status")
                status = status_obj.get("name") if isinstance(status_obj, dict) else ""
                
                approvals.append({
                    "approval_id": page["id"],
                    "document_id": doc_id,
                    "document_name": _get_title("Approval Name"),
                    "status": status,
                    "reason": _get_text("Reason for Review"),
                    "created_at": _get_date("Created At"),
                })
            return approvals
        except NotionServiceError as exc:
            raise ApprovalServiceError(f"Failed to fetch approvals: {exc}") from exc

    async def submit_decision(self, approval_id: str, decision: str, notes: str | None = None) -> dict:
        """Submit a human decision and update the original document status if necessary."""
        try:
            # 1. Fetch current approval item to validate state
            try:
                page = await self.notion_service.get_approval_entry(approval_id)
            except NotionServiceError as exc:
                raise ApprovalServiceError(f"Approval not found: {exc}", status_code=404) from exc
                
            props = page.get("properties", {})
            current_status = props.get("Approval Status", {}).get("status", {}).get("name")
            
            if current_status != ApprovalStatus.PENDING_APPROVAL.value:
                raise ApprovalServiceError(f"Cannot submit decision for approval in state: {current_status}", status_code=400)
                
            doc_relation = props.get("Document", {}).get("relation", [])
            document_id = doc_relation[0]["id"] if doc_relation else None
            
            if not document_id:
                raise ApprovalServiceError("Approval entry is missing document relation.", status_code=500)

            # 2. Update Approval Queue
            logger.info("[APPROVAL] Submitting decision '%s' for approval %s", decision, approval_id)
            now_iso = datetime.now(timezone.utc).isoformat()
            
            await self.notion_service.update_approval_decision(
                approval_id=approval_id,
                decision=decision,
                notes=notes,
                decision_date=now_iso
            )
            
            # 3. Synchronize with DOCUMENT INBOX
            if decision == ApprovalStatus.APPROVED.value:
                logger.info("[APPROVAL] Document approved. Updating inbox status to %s.", DocumentStatus.APPROVED.value)
                await self.notion_service.update_document_status_only(document_id, DocumentStatus.APPROVED.value)
            elif decision == ApprovalStatus.REJECTED.value:
                logger.info("[APPROVAL] Document rejected. Updating inbox status to %s.", DocumentStatus.REJECTED.value)
                await self.notion_service.update_document_status_only(document_id, DocumentStatus.REJECTED.value)
            elif decision == ApprovalStatus.NEEDS_CORRECTION.value:
                logger.info("[APPROVAL] Document marked for correction.")
                # We leave the inbox status as Needs Human Review until it is finally Approved.
                
            return {"success": True, "approval_id": approval_id, "decision": decision}
            
        except NotionServiceError as exc:
            logger.error("[APPROVAL] Notion update failed during decision submission: %s", exc)
            raise ApprovalServiceError(f"Notion API failure: {exc}") from exc
