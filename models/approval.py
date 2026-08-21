"""Centralized human approval queue statuses."""

from enum import Enum


class ApprovalStatus(str, Enum):
    """Valid lifecycle states for an item in the APPROVAL QUEUE."""

    PENDING_APPROVAL = "Pending Approval"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    NEEDS_CORRECTION = "Needs Correction"
