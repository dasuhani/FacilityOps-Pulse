"""
database/models/request.py
--------------------------
ServiceRequest model: the core entity of the platform.
Tracks the full lifecycle of a facility or IT service request.

Extended fields (v2):
  - location_id          FK → locations.id (structured location)
  - assigned_technician_id  FK → users.id (denormalised fast lookup; source
                            of truth is still the assignments table)
  - due_date             Optional SLA deadline set by admin
  - ai_summary           LLM-generated one-paragraph summary of the request
  - ai_recommendation    LLM-generated action recommendation for the technician
"""

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models import Base


class RequestCategory(str, enum.Enum):
    # Facility categories
    ELECTRICAL = "electrical"
    PLUMBING = "plumbing"
    HVAC = "hvac"
    CLEANING = "cleaning"
    SAFETY = "safety"
    EQUIPMENT_MAINTENANCE = "equipment_maintenance"
    # IT categories
    IT_SUPPORT = "it_support"
    NETWORK_WIFI = "network_wifi"
    COMPUTER_DISPLAY = "computer_display"
    # General
    OTHER = "other"


class RequestPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RequestStatus(str, enum.Enum):
    # Workflow statuses aligned with product spec
    SUBMITTED = "submitted"      # Newly created, awaiting admin review
    ASSIGNED = "assigned"        # Technician assigned, not yet started
    IN_PROGRESS = "in_progress"  # Technician actively working
    ON_HOLD = "on_hold"          # Paused (waiting parts, access, etc.)
    RESOLVED = "resolved"        # Work complete, pending requester confirmation
    CLOSED = "closed"            # Confirmed resolved / admin closed
    CANCELLED = "cancelled"      # Voided before work started

    # Legacy alias kept so existing DB rows with status="open" still map
    OPEN = "open"                # synonym for SUBMITTED in legacy data


# Human-readable labels
PRIORITY_LABELS = {
    RequestPriority.LOW: "🟢 Low",
    RequestPriority.MEDIUM: "🟡 Medium",
    RequestPriority.HIGH: "🟠 High",
    RequestPriority.CRITICAL: "🔴 Critical",
}

STATUS_LABELS = {
    RequestStatus.SUBMITTED: "📥 Submitted",
    RequestStatus.OPEN: "📋 Open",          # legacy
    RequestStatus.ASSIGNED: "👤 Assigned",
    RequestStatus.IN_PROGRESS: "🔧 In Progress",
    RequestStatus.ON_HOLD: "⏸ On Hold",
    RequestStatus.RESOLVED: "✅ Resolved",
    RequestStatus.CLOSED: "🔒 Closed",
    RequestStatus.CANCELLED: "❌ Cancelled",
}

# Statuses that count as "active" (not terminal)
ACTIVE_STATUSES = {
    RequestStatus.SUBMITTED,
    RequestStatus.OPEN,
    RequestStatus.ASSIGNED,
    RequestStatus.IN_PROGRESS,
    RequestStatus.ON_HOLD,
}

# Terminal statuses
TERMINAL_STATUSES = {
    RequestStatus.RESOLVED,
    RequestStatus.CLOSED,
    RequestStatus.CANCELLED,
}

CATEGORY_LABELS = {
    RequestCategory.ELECTRICAL: "⚡ Electrical",
    RequestCategory.PLUMBING: "🚿 Plumbing",
    RequestCategory.HVAC: "❄️ HVAC",
    RequestCategory.CLEANING: "🧹 Cleaning",
    RequestCategory.SAFETY: "⚠️ Safety",
    RequestCategory.EQUIPMENT_MAINTENANCE: "🔩 Equipment Maintenance",
    RequestCategory.IT_SUPPORT: "💻 IT Support",
    RequestCategory.NETWORK_WIFI: "📶 Network & Wi-Fi",
    RequestCategory.COMPUTER_DISPLAY: "🖥️ Computer & Display",
    RequestCategory.OTHER: "📦 Other",
}

# Which categories are facility-type vs IT-type (used in AI routing)
FACILITY_CATEGORIES = {
    RequestCategory.ELECTRICAL,
    RequestCategory.PLUMBING,
    RequestCategory.HVAC,
    RequestCategory.CLEANING,
    RequestCategory.SAFETY,
    RequestCategory.EQUIPMENT_MAINTENANCE,
}

IT_CATEGORIES = {
    RequestCategory.IT_SUPPORT,
    RequestCategory.NETWORK_WIFI,
    RequestCategory.COMPUTER_DISPLAY,
}


class ServiceRequest(Base):
    __tablename__ = "service_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Reference number shown in the UI (e.g. "REQ-00042")
    reference_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)

    # Core fields
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(String(256), nullable=False)
    building: Mapped[str | None] = mapped_column(String(128), nullable=True)
    floor_or_room: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Classification
    category: Mapped[RequestCategory] = mapped_column(
        Enum(RequestCategory, name="request_category_enum", create_constraint=False),
        nullable=False,
        default=RequestCategory.OTHER,
    )
    sub_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    department_target: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # AI-generated fields
    ai_suggested_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ai_suggested_priority: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_classification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # v2 AI fields
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Priority & status
    priority: Mapped[RequestPriority] = mapped_column(
        Enum(RequestPriority, name="request_priority_enum", create_constraint=False),
        nullable=False,
        default=RequestPriority.MEDIUM,
    )
    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus, name="request_status_enum", create_constraint=False),
        nullable=False,
        default=RequestStatus.SUBMITTED,
    )

    # Embedding vector stored as a comma-separated string for portability.
    # For production use with pgvector, replace this with a Vector column.
    embedding_str: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships (foreign keys)
    requester_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requester: Mapped["User"] = relationship(
        "User",
        back_populates="submitted_requests",
        foreign_keys=[requester_id],
        lazy="select",
    )

    # v2: structured location FK (optional — legacy free-text fields kept for back-compat)
    location_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    location_obj: Mapped["Location | None"] = relationship(
        "Location",
        back_populates="requests",
        foreign_keys=[location_id],
        lazy="select",
    )

    # v2: denormalised assigned technician for fast single-JOIN lookups.
    # The assignments table remains the authoritative assignment store.
    # This field is kept in sync by assignment_crud.assign_request() and
    # assignment_crud.unassign_request().
    assigned_technician_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_technician: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[assigned_technician_id],
        lazy="select",
    )

    # v2: optional SLA due date set by admin / business rule
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Resolution
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships (back-references)
    assignment: Mapped["Assignment | None"] = relationship(
        "Assignment",
        back_populates="request",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="select",
    )
    status_history: Mapped[list["StatusHistory"]] = relationship(
        "StatusHistory",
        back_populates="request",
        order_by="StatusHistory.changed_at",
        cascade="all, delete-orphan",
        lazy="select",
    )
    # v2 back-references
    comments: Mapped[list["RequestComment"]] = relationship(
        "RequestComment",
        back_populates="request",
        order_by="RequestComment.created_at",
        cascade="all, delete-orphan",
        lazy="select",
    )
    history: Mapped[list["RequestHistory"]] = relationship(
        "RequestHistory",
        back_populates="request",
        order_by="RequestHistory.created_at",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<ServiceRequest id={self.id} ref={self.reference_number!r} "
            f"status={self.status.value}>"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "reference_number": self.reference_number,
            "title": self.title,
            "description": self.description,
            "location": self.location,
            "building": self.building,
            "floor_or_room": self.floor_or_room,
            # v2 structured location
            "location_id": self.location_id,
            "location_display": (
                self.location_obj.display_name() if self.location_obj else None
            ),
            "category": self.category.value,
            "sub_category": self.sub_category,
            "department_target": self.department_target,
            "ai_suggested_category": self.ai_suggested_category,
            "ai_suggested_priority": self.ai_suggested_priority,
            "ai_classification_notes": self.ai_classification_notes,
            "ai_confidence_score": self.ai_confidence_score,
            "ai_summary": self.ai_summary,
            "ai_recommendation": self.ai_recommendation,
            "priority": self.priority.value,
            "status": self.status.value,
            "requester_id": self.requester_id,
            # v2 denormalised assignment
            "assigned_technician_id": self.assigned_technician_id,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "resolution_notes": self.resolution_notes,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
