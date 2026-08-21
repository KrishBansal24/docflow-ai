"""Centralized human approval queue statuses."""

from enum import Enum


class ApprovalDecision(str, Enum):
    """Represents the human decision in the APPROVAL QUEUE."""

    PENDING_DECISION = "Pending Decision"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    NEEDS_CORRECTION = "Needs Correction"
