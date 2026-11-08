"""
database/models/request_history.py
-------------------------------------
RequestHistory model: a dedicated, richer history table that supplements
the existing StatusHistory table.

StatusHistory (existing) tracks status transitions only.
RequestHistory (new) tracks ANY meaningful change to a request:
  - status changes (old_status → new_status)
  - priority overrides
  - (re-)assignments
  - field edits

Every row is immutable once written.

Note: The existing `status_history` table is kept intact to avoid
breaking existing functionality.  The new `request_history` table is
an additive companion, used by the admin audit view and reporting.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models import Base


class HistoryEventType(str, enum.Enum):
    STATUS_CHANGE = "status_change"
    PRIORITY_CHANGE = "priority_change"
    ASSIGNMENT = "assignment"
    REASSIGNMENT = "reassignment"
    UNASSIGNMENT = "unassignment"
    FIELD_EDIT = "field_edit"
    COMMENT_ADDED = "comment_added"
    CREATED = "created"


class RequestHistory(Base):
    __tablename__ = "request_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    request_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("service_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The user who caused this event
    changed_by: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    event_type: Mapped[HistoryEventType] = mapped_column(
        Enum(HistoryEventType, name="history_event_type_enum"),
        nullable=False,
    )

    # Status transition fields (nullable — only set for STATUS_CHANGE)
    old_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Generic diff fields: what changed and to what value
    field_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Human-readable note attached to this event
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    request: Mapped["ServiceRequest"] = relationship(
        "ServiceRequest",
        back_populates="history",
        foreign_keys=[request_id],
        lazy="select",
    )
    actor: Mapped["User"] = relationship(
        "User",
        foreign_keys=[changed_by],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<RequestHistory id={self.id} request_id={self.request_id} "
            f"event={self.event_type.value}>"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "changed_by": self.changed_by,
            "actor_name": self.actor.full_name if self.actor else None,
            "event_type": self.event_type.value,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "field_name": self.field_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
