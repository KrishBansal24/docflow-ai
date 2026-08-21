"""Centralized document workflow statuses.

Every status value written to Notion or returned in API responses MUST come
from this enum.  Using raw strings elsewhere is a bug.
"""

from enum import Enum


class DocumentStatus(str, Enum):
    """Valid lifecycle states for a document in the DOCUMENT INBOX."""

    PROCESSING = "Processing"
    AI_ANALYZED = "AI Analyzed"
    NEEDS_HUMAN_REVIEW = "Needs Human Review"
    AI_ANALYSIS_FAILED = "AI Analysis Failed"
