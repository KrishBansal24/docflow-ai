import logging
from datetime import datetime, timezone

from models.approval import ApprovalDecision
from models.workflow import DecisionStatus
from services.notion import ApprovalNotionService, DocumentNotionService, RunLogNotionService
from services.notion.client import NotionServiceError
from services.email_service import EmailService, EmailServiceError

logger = logging.getLogger(__name__)


class ApprovalServiceError(Exception):
    """Raised when an approval queue operation fails."""
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


class ApprovalService:
    def __init__(self) -> None:
        self.approval_notion = ApprovalNotionService()
        self.document_notion = DocumentNotionService()
        self.run_log_notion = RunLogNotionService()
        self.email_service = EmailService()

    async def queue_document_for_review(
        self, document_id: str, document_name: str, reason: str, priority: str | None = None
    ) -> dict[str, str]:
        """Create a new approval entry if one doesn't exist."""
        try:
            existing = await self.approval_notion.check_existing_approval(document_id)
            if existing:
                logger.info("[APPROVAL] Existing approval entry found for %s (id=%s)", document_id, existing["id"])
                return existing

            logger.info("[APPROVAL] Document requires human review: %s. Creating queue entry.", document_name)
            now_iso = datetime.now(timezone.utc).isoformat()
            
            new_approval = await self.approval_notion.create_approval_entry(
                document_id=document_id,
                document_name=document_name,
                reason=reason,
                created_at=now_iso,
                priority=priority,
            )
            logger.info("[APPROVAL] Approval queue entry created: %s", new_approval["id"])
            return {"id": new_approval["id"], "status": ApprovalDecision.PENDING_DECISION.value}

        except NotionServiceError as exc:
            logger.error("[APPROVAL] Failed to queue document %s: %s", document_name, exc)
            # We raise so the caller knows the queue failed, though we may handle it gracefully upstream.
            raise ApprovalServiceError(f"Could not queue document for approval: {exc}") from exc

    async def get_pending_approvals(self) -> list[dict]:
        """Retrieve all pending approvals."""
        try:
            results = await self.approval_notion.get_pending_approvals()
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
                
                status_obj = props.get("Approval Decision", {}).get("status")
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
                page = await self.approval_notion.get_approval_entry(approval_id)
            except NotionServiceError as exc:
                raise ApprovalServiceError(f"Approval not found: {exc}", status_code=404) from exc
                
            props = page.get("properties", {})
            current_status = props.get("Approval Decision", {}).get("status", {}).get("name")
            
            if current_status != ApprovalDecision.PENDING_DECISION.value:
                raise ApprovalServiceError(f"Cannot submit decision for approval in state: {current_status}", status_code=400)
                
            doc_relation = props.get("Document", {}).get("relation", [])
            document_id = doc_relation[0]["id"] if doc_relation else None
            
            if not document_id:
                raise ApprovalServiceError("Approval entry is missing document relation.", status_code=500)

            # 2. Update Approval Queue
            logger.info("[APPROVAL] Submitting decision '%s' for approval %s", decision, approval_id)
            now_iso = datetime.now(timezone.utc).isoformat()
            
            await self.approval_notion.update_approval_decision(
                approval_id=approval_id,
                decision=decision,
                notes=notes,
                decision_date=now_iso
            )
            
            # 3. Synchronize with DOCUMENT INBOX
            logger.info("[APPROVAL] Document decision submitted. Updating inbox decision status to %s.", DecisionStatus.DECISION_TAKEN.value)
            await self.document_notion.update_decision_status_only(document_id, DecisionStatus.DECISION_TAKEN.value)
                
            # 4. Trigger External Email Action (Phase 7)
            try:
                document = await self.document_notion.get_document(document_id)
                doc_props = document.get("properties", {})
                
                title_prop = doc_props.get("Document Name", {}).get("title", [])
                doc_title = "".join(t.get("plain_text", "") for t in title_prop) if title_prop else "Unknown Document"
                
                department_prop = doc_props.get("Departments", {}).get("multi_select", [])
                departments = [d.get("name") for d in department_prop if d.get("name")]
                
                recipient_emails = set()
                settings = self.email_service.settings
                
                dept_map = {
                    "Finance": settings.email_finance,
                    "IT": settings.email_it,
                    "Legal": settings.email_legal,
                    "HR": settings.email_hr,
                    "Operations": settings.email_operations,
                }
                
                for dept in departments:
                    if email := dept_map.get(dept):
                        recipient_emails.add(email)
                        
                if not recipient_emails:
                    recipient_prop = doc_props.get("Suggested Recipient", {}).get("rich_text", [])
                    if suggested := "".join(t.get("plain_text", "") for t in recipient_prop):
                        recipient_emails.add(suggested)
                        
                if not recipient_emails:
                    if settings.email_default:
                        recipient_emails.add(settings.email_default)
                    elif settings.smtp_from_email:
                        recipient_emails.add(settings.smtp_from_email)
                    else:
                        recipient_emails.add("admin@example.com")
                
                recipients_str = ", ".join(recipient_emails)
                
                if decision == ApprovalDecision.APPROVED.value:
                    self.email_service.send_approval_notification(recipients_str, doc_title, notes)
                    final_decision_status = DecisionStatus.ACTION_COMPLETED.value
                elif decision == ApprovalDecision.NEEDS_CORRECTION.value:
                    self.email_service.send_correction_notification(recipients_str, doc_title, notes)
                    final_decision_status = DecisionStatus.ACTION_COMPLETED.value
                else:
                    # For REJECTED, maybe we just don't send an email, or we do, but let's stick to the spec.
                    final_decision_status = DecisionStatus.DECISION_TAKEN.value
                
                if final_decision_status == DecisionStatus.ACTION_COMPLETED.value:
                    # Update decision status to ACTION_COMPLETED now that email is sent
                    await self.document_notion.update_decision_status_only(document_id, final_decision_status)
                    await self.run_log_notion.create_run_log_entry("Action Completed", "Success", f"Sent email to {recipients_str}", document_id, event_type="Workflow")
                    
            except Exception as e:
                logger.error("[APPROVAL] Failed to send email for %s: %s", approval_id, e)
                await self.run_log_notion.create_run_log_entry("Action Completed", "Failed", f"Failed to send email: {e}", document_id, event_type="Workflow")
                # We won't block the API response for an email failure, but in production we'd queue it.

            await self.run_log_notion.create_run_log_entry("Human Decision", "Success", f"Reviewer decided: {decision}", document_id, event_type="Workflow")
            return {"success": True, "approval_id": approval_id, "decision": decision}
            
        except NotionServiceError as exc:
            logger.error("[APPROVAL] Notion update failed during decision submission: %s", exc)
            raise ApprovalServiceError(f"Notion API failure: {exc}") from exc
