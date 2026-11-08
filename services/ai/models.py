"""
services/ai/models.py
---------------------
Pydantic schemas for validating all LLM JSON responses before they touch
the database or the UI.

These models enforce:
  - Correct field names and types
  - Category and priority values that match the ORM enums
  - Numeric ranges (confidence 0.0–1.0)
  - String length limits to prevent storage bloat

Usage:
    from services.ai.models import ClassificationSchema, PrioritySchema

    # Validate raw LLM JSON:
    try:
        parsed = ClassificationSchema.model_validate_json(raw_text)
    except ValidationError:
        # fall back to defaults
"""

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Classification response schema
# ---------------------------------------------------------------------------

class ClassificationSchema(BaseModel):
    """
    Schema for the AI classification JSON response.

    Fields match the product spec:
      category, summary, priority, urgency_reason,
      recommended_action, confidence
    """

    category: str = Field(
        ...,
        description="One of: electrical, plumbing, hvac, cleaning, safety, "
                    "equipment_maintenance, it_support, network_wifi, "
                    "computer_display, other",
    )
    summary: str = Field(
        ...,
        max_length=500,
        description="Concise one-sentence summary of the request.",
    )
    priority: str = Field(
        default="medium",
        description="One of: critical, high, medium, low",
    )
    urgency_reason: str = Field(
        default="",
        max_length=300,
        description="Why this priority was chosen.",
    )
    recommended_action: str = Field(
        default="",
        max_length=300,
        description="What the technician should do first.",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Model's self-reported confidence 0.0–1.0.",
    )
    # Extra fields the older prompt returned — kept for backward compat
    sub_category: Optional[str] = Field(default=None, max_length=128)
    department: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = Field(default=None, max_length=512)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        v = v.lower().strip()
        valid = {
            "electrical", "plumbing", "hvac", "cleaning", "safety",
            "equipment_maintenance", "it_support", "network_wifi",
            "computer_display", "other",
        }
        if v not in valid:
            return "other"
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in {"critical", "high", "medium", "low"}:
            return "medium"
        return v


# ---------------------------------------------------------------------------
# Priority response schema
# ---------------------------------------------------------------------------

class PrioritySchema(BaseModel):
    """
    Schema for the AI priority recommendation JSON response.
    """

    priority: str = Field(
        ...,
        description="One of: critical, high, medium, low",
    )
    justification: str = Field(
        default="",
        max_length=512,
        description="Why this priority was recommended.",
    )
    escalation_flag: bool = Field(
        default=False,
        description="True if safety or legal risk is present.",
    )

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in {"critical", "high", "medium", "low"}:
            return "medium"
        return v


# ---------------------------------------------------------------------------
# NL Query intent schema
# ---------------------------------------------------------------------------

class NLQueryIntent(BaseModel):
    """
    Schema for the LLM's classification of a natural-language query into
    one of the predefined intent types.  The LLM never generates SQL — it
    only picks an intent and optional parameters.
    """

    intent: str = Field(
        ...,
        description="One of: category_open_count, location_category_count, "
                    "technician_workload, status_summary, priority_summary, "
                    "unknown",
    )
    category: Optional[str] = Field(
        default=None,
        description="Category name if the intent is category-related.",
    )
    location: Optional[str] = Field(
        default=None,
        description="Location keyword if the intent is location-related.",
    )

    @field_validator("intent")
    @classmethod
    def validate_intent(cls, v: str) -> str:
        v = v.lower().strip()
        valid = {
            "category_open_count", "location_category_count",
            "technician_workload", "status_summary",
            "priority_summary", "unknown",
        }
        if v not in valid:
            return "unknown"
        return v


# ---------------------------------------------------------------------------
# Input sanitization helper
# ---------------------------------------------------------------------------

def sanitize_for_llm(text: str, max_length: int = 2000) -> str:
    """
    Sanitize user-submitted text before sending it to the LLM.

    - Truncates to max_length to prevent token-bombing.
    - Strips common prompt-injection patterns.
    - Does NOT follow any instructions found in the text.

    This is a defense-in-depth measure, not a complete solution.  The
    system prompt must also instruct the model to treat the user content
    as data, not instructions.
    """
    if not text:
        return ""

    text = text.strip()[:max_length]

    # Remove common injection patterns (case-insensitive)
    injection_patterns = [
        r"(?i)ignore (?:all |the )?(?:previous |above )?instructions",
        r"(?i)you are (?:now |a )?(?:different |new )?",
        r"(?i)system\s*:",
        r"(?i)assistant\s*:",
        r"(?i)disregard (?:the )?(?:previous|above|system)",
        r"(?i)act as (?:if you are|a)",
    ]
    for pattern in injection_patterns:
        text = re.sub(pattern, "[filtered]", text)

    return text
