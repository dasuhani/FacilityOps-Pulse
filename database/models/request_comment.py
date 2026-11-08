"""
database/models/request_comment.py
-------------------------------------
RequestComment model: threaded comments on a service request.

Any authenticated user who has access to a request can post a comment.
Comments are append-only (no edit/delete) to preserve the audit trail.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models import Base


class RequestComment(Base):
    __tablename__ = "request_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    request_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("service_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # The comment body — required, no upper limit at DB level
    comment: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    request: Mapped["ServiceRequest"] = relationship(
        "ServiceRequest",
        back_populates="comments",
        foreign_keys=[request_id],
        lazy="select",
    )
    user: Mapped["User"] = relationship(
        "User",
        back_populates="comments",
        foreign_keys=[user_id],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<RequestComment id={self.id} request_id={self.request_id} "
            f"user_id={self.user_id}>"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "user_id": self.user_id,
            # user_name populated by the business/CRUD layer when needed
            "user_name": (
                self.user.full_name
                if self.user is not None
                else None
            ),
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
