"""
database/models/status_history.py
-----------------------------------
StatusHistory model: immutable audit log of every status transition
and work note added to a ServiceRequest.
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models import Base
from database.models.request import RequestStatus


class StatusHistory(Base):
    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign keys
    request_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("service_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    changed_by_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Transition
    previous_status: Mapped[str | None] = mapped_column(
        Enum(RequestStatus, name="request_status_enum", create_constraint=False),
        nullable=True,   # NULL on the initial "created" event
    )
    new_status: Mapped[str] = mapped_column(
        Enum(RequestStatus, name="request_status_enum", create_constraint=False),
        nullable=False,
    )

    # Free-text note attached to this transition (e.g. technician work notes)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source of change: 'system', 'requester', 'technician', 'admin'
    changed_by_role: Mapped[str | None] = mapped_column(String(32), nullable=True)

    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    request: Mapped["ServiceRequest"] = relationship(
        "ServiceRequest",
        back_populates="status_history",
        foreign_keys=[request_id],
        lazy="select",
    )
    changed_by: Mapped["User"] = relationship(
        "User",
        foreign_keys=[changed_by_id],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<StatusHistory id={self.id} request_id={self.request_id} "
            f"{self.previous_status!r} → {self.new_status!r}>"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "changed_by_id": self.changed_by_id,
            "changed_by_role": self.changed_by_role,
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "note": self.note,
            "changed_at": self.changed_at.isoformat() if self.changed_at else None,
        }
