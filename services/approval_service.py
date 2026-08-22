import logging
import asyncio
import time
from datetime import datetime, timezone

from models.approval import ApprovalDecision
from models.workflow import DecisionStatus
from services.notion import ApprovalNotionService, DocumentNotionService, RunLogNotionService
from services.notion.client import NotionServiceError
from services.notion.directory import DirectoryNotionService
from services.email_service import EmailService, EmailServiceError
from services.whatsapp_service import WhatsAppService, WhatsAppServiceError

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
        self.directory_notion = DirectoryNotionService()
        self.email_service = EmailService()
        self.whatsapp_service = WhatsAppService()
        self.in_flight_approvals: set[str] = set()
        self._routing_cache = None
        self._routing_cache_time = 0

    async def queue_document_for_review(
        self, document_id: str, document_name: str, reason: str, priority: str | None = None, suggested_recipient: str | None = None, sender: str | None = None
    ) -> dict[str, str]:
        """Create a new approval entry if one doesn't exist."""
        try:
            existing = await self.approval_notion.check_existing_approval(document_id)
            if existing:
                logger.info("[APPROVAL] Existing approval entry found for %s (id=%s)", document_id, existing["id"])
                return existing

            logger.info("[APPROVAL] Document requires human review: %s. Creating queue entry.", document_name)
            now_iso = datetime.now(timezone.utc).isoformat()
            
            approval_title = suggested_recipient if suggested_recipient and suggested_recipient != "Unknown" else f"Approval: {document_name}"
            
            new_approval = await self.approval_notion.create_approval_entry(
                document_id=document_id,
                document_name=approval_title,
                reason=reason,
                created_at=now_iso,
                priority=priority,
                sender=sender,
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

    async def submit_decision(self, approval_id: str, decision: str, notes: str | None = None, bypass_status_check: bool = False) -> dict:
        """Submit a human decision and update the original document status if necessary."""
        try:
            # 1. Fetch current approval item to validate state
            try:
                page = await self.approval_notion.get_approval_entry(approval_id)
            except NotionServiceError as exc:
                raise ApprovalServiceError(f"Approval not found: {exc}", status_code=404) from exc
                
            props = page.get("properties", {})
            current_status = props.get("Approval Decision", {}).get("status", {}).get("name")
            
            if not bypass_status_check and current_status != ApprovalDecision.PENDING_DECISION.value:
                raise ApprovalServiceError(f"Cannot submit decision for approval in state: {current_status}", status_code=400)
                
            doc_relation = props.get("Document", {}).get("relation", [])
            document_id = doc_relation[0]["id"] if doc_relation else None
            
            if not document_id:
                raise ApprovalServiceError("Approval entry is missing document relation.", status_code=500)

            # 2 & 3. Update Approval Queue and Document Inbox Concurrently
            logger.info("[APPROVAL] Submitting decision '%s' for approval %s and updating document", decision, approval_id)
            now_iso = datetime.now(timezone.utc).isoformat()
            
            await asyncio.gather(
                self.approval_notion.update_approval_decision(
                    approval_id=approval_id,
                    decision=decision,
                    notes=notes,
                    decision_date=now_iso
                ),
                self.document_notion.update_decision_status_only(document_id, DecisionStatus.DECISION_TAKEN.value)
            )
                
            # 4. Trigger External Email Action (Phase 7)
            try:
                document = await self.document_notion.get_document(document_id)
                doc_props = document.get("properties", {})
                
                title_prop = doc_props.get("Document Name", {}).get("title", [])
                doc_title = "".join(t.get("plain_text", "") for t in title_prop) if title_prop else "Unknown Document"
                
                department_prop = doc_props.get("Department", {}).get("multi_select", []) or doc_props.get("Departments", {}).get("multi_select", [])
                departments = [d.get("name") for d in department_prop if d.get("name")]
                primary_dept = departments[0] if departments else None
                
                recipient_emails = set()
                recipient_whatsapps = set()
                settings = self.email_service.settings
                
                # Fetch routing rules from Notion dynamically (with 60s cache)
                if not self._routing_cache or time.time() - self._routing_cache_time > 60:
                    self._routing_cache = await self.directory_notion.get_department_routing()
                    self._routing_cache_time = time.time()
                routing_map = self._routing_cache
                
                for dept in departments:
                    if dept in routing_map:
                        recipient_emails.update(routing_map[dept]["emails"])
                        recipient_whatsapps.update(routing_map[dept]["whatsapp"])
                        
                if not recipient_emails and not recipient_whatsapps:
                    recipient_prop = doc_props.get("Suggested Recipient", {}).get("rich_text", [])
                    if suggested := "".join(t.get("plain_text", "") for t in recipient_prop):
                        if "@" in suggested:
                            recipient_emails.add(suggested)
                        elif any(char.isdigit() for char in suggested):
                            if not suggested.startswith("whatsapp:"):
                                suggested = f"whatsapp:{suggested}"
                            recipient_whatsapps.add(suggested)
                        else:
                            logger.info("[APPROVAL] Suggested Recipient '%s' is neither email nor WhatsApp. Falling back to defaults.", suggested)
                        
                if not recipient_emails and not recipient_whatsapps:
                    if settings.smtp_from_email:
                        recipient_emails.add(settings.smtp_from_email)
                
                recipients_str = ", ".join(recipient_emails)
                whatsapp_str = ", ".join(recipient_whatsapps)
                
                if decision == ApprovalDecision.APPROVED.value:
                    for wa in recipient_whatsapps:
                        asyncio.create_task(self.whatsapp_service.send_approval_notification(wa, doc_title, notes, department=primary_dept))
                    if recipients_str:
                        asyncio.create_task(asyncio.to_thread(self.email_service.send_approval_notification, recipients_str, doc_title, notes, department=primary_dept))
                    final_decision_status = DecisionStatus.ACTION_COMPLETED.value
                elif decision == ApprovalDecision.NEEDS_CORRECTION.value:
                    for wa in recipient_whatsapps:
                        asyncio.create_task(self.whatsapp_service.send_correction_notification(wa, doc_title, notes))
                    if recipients_str:
                        asyncio.create_task(asyncio.to_thread(self.email_service.send_correction_notification, recipients_str, doc_title, notes))
                    final_decision_status = DecisionStatus.ACTION_COMPLETED.value
                else:
                    # For REJECTED
                    final_decision_status = DecisionStatus.DECISION_TAKEN.value
                
                if final_decision_status == DecisionStatus.ACTION_COMPLETED.value:
                    # Update decision status to ACTION_COMPLETED and write to run log concurrently
                    await asyncio.gather(
                        self.document_notion.update_decision_status_only(document_id, final_decision_status),
                        self.run_log_notion.create_run_log_entry("Action Completed", "Success", f"Sent notifications to: emails=[{recipients_str}] whatsapp=[{whatsapp_str}]", document_id, event_type="Workflow")
                    )
                    
            except Exception as e:
                logger.error("[APPROVAL] Failed to send notifications for %s: %s", approval_id, e)
                await self.run_log_notion.create_run_log_entry("Action Completed", "Failed", f"Failed to send notifications: {e}", document_id, event_type="Workflow")
                # We won't block the API response for an email failure, but in production we'd queue it.

            asyncio.create_task(self.run_log_notion.create_run_log_entry("Human Decision", "Success", f"Reviewer decided: {decision}", document_id, event_type="Workflow"))
            return {"success": True, "approval_id": approval_id, "decision": decision}
            
        except NotionServiceError as exc:
            logger.error("[APPROVAL] Notion update failed during decision submission: %s", exc)
            raise ApprovalServiceError(f"Notion API failure: {exc}") from exc

    async def process_notion_updates(self) -> None:
        """Polls Notion for any unprocessed decisions and handles them."""
        try:
            unprocessed = await self.approval_notion.get_unprocessed_decisions()
            for approval in unprocessed:
                approval_id = approval["id"]
                props = approval.get("properties", {})
                
                decision_obj = props.get("Approval Decision", {}).get("status", {})
                decision = decision_obj.get("name") if decision_obj else None
                
                notes_obj = props.get("Reviewer Notes", {}).get("rich_text", [])
                notes = "".join(t.get("plain_text", "") for t in notes_obj) if notes_obj else None
                
                if not decision or decision == ApprovalDecision.PENDING_DECISION.value:
                    continue
                    
                if approval_id in self.in_flight_approvals:
                    continue
                    
                self.in_flight_approvals.add(approval_id)
                logger.info("[APPROVAL] Found unprocessed Notion decision '%s' for approval %s", decision, approval_id)
                
                async def _process_approval(app_id=approval_id, dec=decision, app_notes=notes):
                    try:
                        await self.submit_decision(app_id, dec, app_notes, bypass_status_check=True)
                        await self.approval_notion.mark_approval_processed(app_id)
                        logger.info("[APPROVAL] Successfully processed and marked %s", app_id)
                    except Exception as exc:
                        logger.error("[APPROVAL] Failed to process decision for %s: %s", app_id, exc)
                    finally:
                        self.in_flight_approvals.discard(app_id)
                        
                asyncio.create_task(_process_approval())
        except Exception as exc:
            logger.error("[APPROVAL] Polling Notion failed: %s", exc)
