"""
database/models/audit_log.py
------------------------------
AuditLog model: platform-wide security and operational audit trail.

Every significant action (login, user creation, password reset, etc.)
is appended here.  Records are immutable.

Distinct from RequestHistory which is request-scoped.
AuditLog is org-wide and captures user management events, auth events,
and administrative operations.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # The user who performed the action (nullable: system events have no user)
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Short action identifier — e.g. "user.login", "user.created", "request.cancelled"
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # The type of entity affected — e.g. "user", "request", "assignment"
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # The PK of the affected entity
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Extra context: IP address, user agent, changed fields, etc.
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Outcome: "success" | "failure" | "denied"
    outcome: Mapped[str] = mapped_column(
        String(16), nullable=False, default="success"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    # Optional relationship — omit if user_id is NULL
    user: Mapped["User | None"] = relationship(
        "User",
        back_populates="audit_entries",
        foreign_keys=[user_id],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} action={self.action!r} "
            f"user_id={self.user_id} outcome={self.outcome!r}>"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "detail": self.detail,
            "outcome": self.outcome,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
