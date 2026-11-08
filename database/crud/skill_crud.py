"""
database/crud/skill_crud.py
-----------------------------
All database operations for the TechnicianSkill model.
"""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.technician_skill import TechnicianSkill, SkillCategory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_skills_for_technician(
    session: Session, technician_id: int
) -> list[TechnicianSkill]:
    stmt = (
        select(TechnicianSkill)
        .where(TechnicianSkill.technician_id == technician_id)
        .order_by(TechnicianSkill.skill_category)
    )
    return list(session.scalars(stmt).all())


def get_skill_categories_for_technician(
    session: Session, technician_id: int
) -> list[str]:
    """Return just the skill category values for quick lookup."""
    skills = get_skills_for_technician(session, technician_id)
    return [s.skill_category.value for s in skills]


def get_technicians_with_skill(
    session: Session, skill_category: SkillCategory
) -> list[int]:
    """Return technician_ids that have a specific skill."""
    stmt = (
        select(TechnicianSkill.technician_id)
        .where(TechnicianSkill.skill_category == skill_category)
        .distinct()
    )
    return list(session.scalars(stmt).all())


def skill_exists(
    session: Session,
    technician_id: int,
    skill_category: SkillCategory,
) -> bool:
    stmt = (
        select(TechnicianSkill.id)
        .where(
            TechnicianSkill.technician_id == technician_id,
            TechnicianSkill.skill_category == skill_category,
        )
        .limit(1)
    )
    return session.scalar(stmt) is not None


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def add_skill(
    session: Session,
    technician_id: int,
    skill_category: SkillCategory,
    notes: Optional[str] = None,
) -> TechnicianSkill:
    """
    Add a skill to a technician.
    Raises ValueError if the technician already has that skill.
    """
    if skill_exists(session, technician_id, skill_category):
        raise ValueError(
            f"Technician id={technician_id} already has skill '{skill_category.value}'."
        )

    skill = TechnicianSkill(
        technician_id=technician_id,
        skill_category=skill_category,
        notes=notes.strip() if notes else None,
    )
    session.add(skill)
    session.flush()
    logger.info(
        "Added skill '%s' to technician id=%s",
        skill_category.value, technician_id,
    )
    return skill


def add_skills_bulk(
    session: Session,
    technician_id: int,
    skill_categories: list[SkillCategory],
) -> list[TechnicianSkill]:
    """
    Add multiple skills to a technician, silently skipping duplicates.
    Returns the list of newly created TechnicianSkill objects.
    """
    created = []
    for cat in skill_categories:
        if not skill_exists(session, technician_id, cat):
            skill = TechnicianSkill(technician_id=technician_id, skill_category=cat)
            session.add(skill)
            created.append(skill)
    if created:
        session.flush()
        logger.info(
            "Added %d skill(s) to technician id=%s", len(created), technician_id
        )
    return created


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def remove_skill(
    session: Session,
    technician_id: int,
    skill_category: SkillCategory,
) -> None:
    """Remove a specific skill from a technician. No-op if not found."""
    stmt = (
        select(TechnicianSkill)
        .where(
            TechnicianSkill.technician_id == technician_id,
            TechnicianSkill.skill_category == skill_category,
        )
    )
    skill = session.scalar(stmt)
    if skill:
        session.delete(skill)
        session.flush()
        logger.info(
            "Removed skill '%s' from technician id=%s",
            skill_category.value, technician_id,
        )


def remove_all_skills(session: Session, technician_id: int) -> int:
    """Remove all skills for a technician. Returns count removed."""
    skills = get_skills_for_technician(session, technician_id)
    for s in skills:
        session.delete(s)
    if skills:
        session.flush()
    logger.info(
        "Removed %d skill(s) from technician id=%s", len(skills), technician_id
    )
    return len(skills)
