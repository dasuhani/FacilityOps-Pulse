"""
database/models/assignment.py
------------------------------
Assignment model: links a ServiceRequest to a Technician.
One request has at most one active assignment at a time.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models import Base


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign keys
    request_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("service_requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,   # one active assignment per request
        index=True,
    )
    technician_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assigned_by_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Notes from the admin who made the assignment
    assignment_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Estimated completion date (optional)
    estimated_completion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamps
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    request: Mapped["ServiceRequest"] = relationship(
        "ServiceRequest",
        back_populates="assignment",
        foreign_keys=[request_id],
        lazy="select",
    )
    technician: Mapped["User"] = relationship(
        "User",
        back_populates="assignments",
        foreign_keys=[technician_id],
        lazy="select",
    )
    assigned_by: Mapped["User"] = relationship(
        "User",
        foreign_keys=[assigned_by_id],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<Assignment id={self.id} request_id={self.request_id} "
            f"technician_id={self.technician_id}>"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "technician_id": self.technician_id,
            "assigned_by_id": self.assigned_by_id,
            "assignment_notes": self.assignment_notes,
            "estimated_completion": (
                self.estimated_completion.isoformat() if self.estimated_completion else None
            ),
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
        }
