from typing import Any

from fastapi import APIRouter, HTTPException, BackgroundTasks
from models.schemas import ApprovalDecisionRequest, ApprovalListResponse
from services.approval_service import ApprovalService, ApprovalServiceError

router = APIRouter(prefix="/approvals", tags=["Approvals"])
approval_service = ApprovalService()


@router.get("", response_model=ApprovalListResponse)
async def get_pending_approvals() -> ApprovalListResponse:
    """Retrieve all pending documents requiring human review."""
    try:
        approvals = await approval_service.get_pending_approvals()
        return ApprovalListResponse(approvals=approvals)
    except ApprovalServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/{approval_id}/decision")
async def submit_approval_decision(
    approval_id: str, 
    request: ApprovalDecisionRequest,
    background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Submit a human decision for a pending approval (instant return)."""
    
    async def process_decision_bg() -> None:
        try:
            await approval_service.submit_decision(
                approval_id=approval_id,
                decision=request.decision,
                notes=request.reviewer_notes
            )
        except Exception as exc:
            print(f"Background approval processing failed: {exc}")
            
    background_tasks.add_task(process_decision_bg)
    
    return {"success": True, "approval_id": approval_id, "decision": request.decision, "status": "processing"}
