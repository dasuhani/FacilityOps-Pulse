"""
database/crud/location_crud.py
--------------------------------
All database operations for the Location model.
"""

import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models.location import Location

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_location_by_id(session: Session, location_id: int) -> Optional[Location]:
    return session.get(Location, location_id)


def get_all_locations(
    session: Session,
    active_only: bool = True,
    building_name: Optional[str] = None,
) -> list[Location]:
    stmt = select(Location).order_by(Location.building_name, Location.floor, Location.area)
    if active_only:
        stmt = stmt.where(Location.is_active == 1)
    if building_name:
        stmt = stmt.where(Location.building_name.ilike(f"%{building_name.strip()}%"))
    return list(session.scalars(stmt).all())


def get_distinct_buildings(session: Session) -> list[str]:
    """Return sorted list of unique building names (active only)."""
    stmt = (
        select(Location.building_name)
        .where(Location.is_active == 1)
        .distinct()
        .order_by(Location.building_name)
    )
    return list(session.scalars(stmt).all())


def search_locations(session: Session, query: str) -> list[Location]:
    """Full-text search across building_name, floor, area."""
    q = f"%{query.strip()}%"
    stmt = (
        select(Location)
        .where(Location.is_active == 1)
        .where(
            Location.building_name.ilike(q)
            | Location.floor.ilike(q)
            | Location.area.ilike(q)
        )
        .order_by(Location.building_name, Location.floor)
        .limit(50)
    )
    return list(session.scalars(stmt).all())


def count_locations(session: Session, active_only: bool = True) -> int:
    stmt = select(func.count(Location.id))
    if active_only:
        stmt = stmt.where(Location.is_active == 1)
    return session.scalar(stmt) or 0


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_location(
    session: Session,
    building_name: str,
    floor: Optional[str] = None,
    area: Optional[str] = None,
    description: Optional[str] = None,
) -> Location:
    """
    Create a new location.
    Raises ValueError if building_name is empty.
    """
    building_name = building_name.strip()
    if not building_name:
        raise ValueError("building_name must not be empty.")

    loc = Location(
        building_name=building_name,
        floor=floor.strip() if floor else None,
        area=area.strip() if area else None,
        description=description.strip() if description else None,
        is_active=1,
    )
    session.add(loc)
    session.flush()
    logger.info(
        "Created location id=%s '%s'", loc.id, loc.display_name()
    )
    return loc


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_location(
    session: Session,
    location_id: int,
    building_name: Optional[str] = None,
    floor: Optional[str] = None,
    area: Optional[str] = None,
    description: Optional[str] = None,
) -> Location:
    loc = get_location_by_id(session, location_id)
    if not loc:
        raise ValueError(f"Location id={location_id} not found.")

    if building_name is not None:
        val = building_name.strip()
        if not val:
            raise ValueError("building_name must not be empty.")
        loc.building_name = val
    if floor is not None:
        loc.floor = floor.strip() or None
    if area is not None:
        loc.area = area.strip() or None
    if description is not None:
        loc.description = description.strip() or None

    session.flush()
    logger.info("Updated location id=%s", location_id)
    return loc


def set_location_active(
    session: Session, location_id: int, active: bool
) -> Location:
    loc = get_location_by_id(session, location_id)
    if not loc:
        raise ValueError(f"Location id={location_id} not found.")
    loc.is_active = 1 if active else 0
    session.flush()
    logger.info(
        "Location id=%s set is_active=%s", location_id, active
    )
    return loc
