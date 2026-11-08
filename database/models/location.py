"""
database/models/location.py
----------------------------
Location model: represents a physical place in the organisation
(building → floor → area).

ServiceRequests reference a Location by FK so that locations can be
managed centrally (renamed, merged, retired) without touching every
individual request.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models import Base


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Hierarchical address components
    building_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    floor: Mapped[str | None] = mapped_column(String(32), nullable=True)
    area: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Optional free-text description / directions
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Soft-delete flag — deactivated locations stay in historical records
    is_active: Mapped[bool] = mapped_column(
        "is_active",
        Integer,  # stored as SMALLINT for broad DB compatibility
        nullable=False,
        default=1,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Back-reference: requests that list this location
    requests: Mapped[list["ServiceRequest"]] = relationship(
        "ServiceRequest",
        back_populates="location_obj",
        foreign_keys="ServiceRequest.location_id",
        lazy="select",
    )

    def __repr__(self) -> str:
        parts = [self.building_name]
        if self.floor:
            parts.append(f"Floor {self.floor}")
        if self.area:
            parts.append(self.area)
        return f"<Location id={self.id} {' / '.join(parts)!r}>"

    def display_name(self) -> str:
        """Human-readable label for dropdowns and tables."""
        parts = [self.building_name]
        if self.floor:
            parts.append(f"Floor {self.floor}")
        if self.area:
            parts.append(self.area)
        return " › ".join(parts)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "building_name": self.building_name,
            "floor": self.floor,
            "area": self.area,
            "description": self.description,
            "is_active": bool(self.is_active),
            "display_name": self.display_name(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
