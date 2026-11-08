"""
database/models/technician_skill.py
-------------------------------------
TechnicianSkill model: records skill categories for each technician.

One technician can have multiple skill entries (e.g. "plumbing",
"electrical", "network"). Used for smart assignment suggestions.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models import Base


class SkillCategory(str, enum.Enum):
    # Facility skills
    PLUMBING = "plumbing"
    ELECTRICAL = "electrical"
    HVAC = "hvac"
    CARPENTRY = "carpentry"
    PAINTING = "painting"
    CLEANING = "cleaning"
    ELEVATOR = "elevator"
    GENERAL_MAINTENANCE = "general_maintenance"
    # IT skills
    NETWORKING = "networking"
    HARDWARE = "hardware"
    SOFTWARE = "software"
    SECURITY_SYSTEMS = "security_systems"
    AV_EQUIPMENT = "av_equipment"
    SERVERS = "servers"
    # Safety
    SAFETY_INSPECTION = "safety_inspection"
    FIRE_SYSTEMS = "fire_systems"
    # Generic
    OTHER = "other"


class TechnicianSkill(Base):
    __tablename__ = "technician_skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    technician_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    skill_category: Mapped[SkillCategory] = mapped_column(
        Enum(SkillCategory, name="skill_category_enum"),
        nullable=False,
    )

    # Optional notes (e.g. "Certified electrician – 240V only")
    notes: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationship back to User
    technician: Mapped["User"] = relationship(
        "User",
        back_populates="skills",
        foreign_keys=[technician_id],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<TechnicianSkill id={self.id} "
            f"tech_id={self.technician_id} skill={self.skill_category.value}>"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "technician_id": self.technician_id,
            "skill_category": self.skill_category.value,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
