"""Centralized document workflow statuses.

Every status value written to Notion or returned in API responses MUST come
from this enum.  Using raw strings elsewhere is a bug.
"""

from enum import Enum


class ProcessingStatus(str, Enum):
    """The technical result of document processing."""

    PROCESSING = "Processing"
    AI_ANALYZED = "AI Analyzed"
    NEEDS_HUMAN_REVIEW = "Needs Human Review"
    AI_ANALYSIS_FAILED = "AI Analysis Failed"


class DecisionStatus(str, Enum):
    """Whether a human has completed the review."""

    PENDING_DECISION = "Pending Decision"
    DECISION_TAKEN = "Decision Taken"
    ACTION_COMPLETED = "Action Completed"
