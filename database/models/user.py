"""
database/models/user.py
-----------------------
User model: stores all platform users across the three roles
(Requester, Technician, Administrator).
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models import Base


class UserRole(str, enum.Enum):
    REQUESTER = "requester"
    TECHNICIAN = "technician"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Authentication fields
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)

    # Profile
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Role & status
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role_enum"),
        nullable=False,
        default=UserRole.REQUESTER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Timestamps — stored as UTC
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    submitted_requests: Mapped[list["ServiceRequest"]] = relationship(
        "ServiceRequest",
        back_populates="requester",
        foreign_keys="ServiceRequest.requester_id",
        lazy="select",
    )
    assignments: Mapped[list["Assignment"]] = relationship(
        "Assignment",
        back_populates="technician",
        foreign_keys="Assignment.technician_id",
        lazy="select",
    )
    # v2 back-references
    skills: Mapped[list["TechnicianSkill"]] = relationship(
        "TechnicianSkill",
        back_populates="technician",
        foreign_keys="TechnicianSkill.technician_id",
        cascade="all, delete-orphan",
        lazy="select",
    )
    comments: Mapped[list["RequestComment"]] = relationship(
        "RequestComment",
        back_populates="user",
        foreign_keys="RequestComment.user_id",
        lazy="select",
    )
    audit_entries: Mapped[list["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="user",
        foreign_keys="AuditLog.user_id",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} role={self.role.value}>"

    def to_dict(self) -> dict:
        """Return a safe, serialisable dict (no password hash)."""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "department": self.department,
            "phone": self.phone,
            "role": self.role.value,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }
