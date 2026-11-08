"""
services/ai/technician_recommender.py
--------------------------------------
Recommends technicians for a service request based on:

  1. Skill match — does the technician have a skill category that
     matches the request's category?
  2. Current workload — how many open requests are already assigned?
  3. Category alignment — facility vs IT specialty.

The recommender NEVER assigns a technician.  It returns ranked
recommendations with human-readable reasons.  An administrator must
approve every assignment.

No LLM is used here — the recommendation is fully deterministic and
explainable.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from database.crud.user_crud import get_technicians
from database.crud.skill_crud import get_skill_categories_for_technician
from database.crud.assignment_crud import get_technician_open_workload
from database.models.request import RequestCategory
from database.models.technician_skill import SkillCategory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Category → Skill mapping
# ---------------------------------------------------------------------------

# Maps each RequestCategory to the SkillCategory values that are relevant.
# A technician with ANY of these skills is a strong match.
CATEGORY_TO_SKILLS: dict[str, set[str]] = {
    RequestCategory.ELECTRICAL.value: {
        SkillCategory.ELECTRICAL.value,
        SkillCategory.GENERAL_MAINTENANCE.value,
    },
    RequestCategory.PLUMBING.value: {
        SkillCategory.PLUMBING.value,
        SkillCategory.GENERAL_MAINTENANCE.value,
    },
    RequestCategory.HVAC.value: {
        SkillCategory.HVAC.value,
        SkillCategory.GENERAL_MAINTENANCE.value,
    },
    RequestCategory.CLEANING.value: {
        SkillCategory.CLEANING.value,
    },
    RequestCategory.SAFETY.value: {
        SkillCategory.SAFETY_INSPECTION.value,
        SkillCategory.FIRE_SYSTEMS.value,
    },
    RequestCategory.EQUIPMENT_MAINTENANCE.value: {
        SkillCategory.GENERAL_MAINTENANCE.value,
        SkillCategory.ELEVATOR.value,
        SkillCategory.CARPENTRY.value,
    },
    RequestCategory.IT_SUPPORT.value: {
        SkillCategory.HARDWARE.value,
        SkillCategory.SOFTWARE.value,
    },
    RequestCategory.NETWORK_WIFI.value: {
        SkillCategory.NETWORKING.value,
        SkillCategory.SERVERS.value,
    },
    RequestCategory.COMPUTER_DISPLAY.value: {
        SkillCategory.AV_EQUIPMENT.value,
        SkillCategory.HARDWARE.value,
    },
    RequestCategory.OTHER.value: {
        SkillCategory.OTHER.value,
        SkillCategory.GENERAL_MAINTENANCE.value,
    },
}

# Max workload before a technician's score is penalized heavily
MAX_PREFERRED_WORKLOAD = 5


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class TechnicianRecommendation:
    """A single technician recommendation with score and reasons."""
    technician_id: int
    technician_name: str
    score: float                          # 0.0 – 1.0
    skill_match: bool
    skills_matched: list = field(default_factory=list)
    current_workload: int = 0
    reasons: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recommend_technicians(
    session: Session,
    request_category: str,
    top_k: int = 3,
) -> list[TechnicianRecommendation]:
    """
    Recommend technicians for a request based on skills and workload.

    Parameters
    ----------
    session : SQLAlchemy Session
        Open database session.
    request_category : str
        The RequestCategory value (e.g. "plumbing", "it_support").
    top_k : int
        Maximum number of recommendations to return.

    Returns
    -------
    list[TechnicianRecommendation]
        Sorted by score descending.  Each includes:
          - technician_id, technician_name
          - score (0.0–1.0, higher = better match)
          - skill_match (bool)
          - skills_matched (list of skill category strings)
          - current_workload (int — open assigned requests)
          - reasons (list of human-readable explanation strings)

    This function NEVER assigns a technician.  It only recommends.
    The administrator must approve every assignment.
    """
    # Get all active technicians
    technicians = get_technicians(session, active_only=True)
    if not technicians:
        return []

    # Get current workload for all technicians
    workload = get_technician_open_workload(session)

    # Determine required skills for this category
    required_skills = CATEGORY_TO_SKILLS.get(
        request_category, {SkillCategory.OTHER.value}
    )

    recommendations: list[TechnicianRecommendation] = []

    for tech in technicians:
        # Get this technician's skills
        tech_skills = set(
            get_skill_categories_for_technician(session, tech.id)
        )

        # Find matching skills
        matched_skills = required_skills & tech_skills
        has_skill_match = len(matched_skills) > 0

        # Current workload
        current_load = workload.get(tech.id, 0)

        # --- Scoring ---
        # Skill match: 0.6 if matched, 0.0 if not
        skill_score = 0.6 if has_skill_match else 0.0

        # Workload score: starts at 0.4, decreases as workload increases
        # 0 open → 0.4, 1 → 0.36, 2 → 0.32, ..., 5+ → 0.0
        workload_score = max(0.0, 0.4 * (1 - current_load / MAX_PREFERRED_WORKLOAD))

        # Bonus for exact skill match (not just general_maintenance)
        exact_match_bonus = 0.0
        if has_skill_match:
            # If they have a specific skill (not just general), add bonus
            specific_skills = matched_skills - {SkillCategory.GENERAL_MAINTENANCE.value, SkillCategory.OTHER.value}
            if specific_skills:
                exact_match_bonus = 0.1

        total_score = skill_score + workload_score + exact_match_bonus
        total_score = min(1.0, total_score)

        # Build reasons
        reasons: list[str] = []
        if has_skill_match:
            reasons.append(
                f"Has matching skill(s): {', '.join(sorted(matched_skills))}"
            )
        else:
            reasons.append("No specific skill match for this category")

        if current_load == 0:
            reasons.append("No currently open assignments — available immediately")
        elif current_load <= 2:
            reasons.append(f"Light workload ({current_load} open request(s))")
        elif current_load <= MAX_PREFERRED_WORKLOAD:
            reasons.append(f"Moderate workload ({current_load} open request(s))")
        else:
            reasons.append(f"Heavy workload ({current_load} open request(s)) — consider alternatives")

        if exact_match_bonus > 0:
            reasons.append("Exact skill specialization match (bonus)")

        recommendations.append(TechnicianRecommendation(
            technician_id=tech.id,
            technician_name=tech.full_name,
            score=round(total_score, 3),
            skill_match=has_skill_match,
            skills_matched=sorted(matched_skills),
            current_workload=current_load,
            reasons=reasons,
        ))

    # Sort by score descending
    recommendations.sort(key=lambda r: r.score, reverse=True)

    return recommendations[:top_k]


def get_recommendation_summary(rec: TechnicianRecommendation) -> str:
    """Return a one-line summary string for UI display."""
    parts = [f"{rec.technician_name} (score: {rec.score:.2f})"]
    if rec.skill_match:
        parts.append(f"skills: {', '.join(rec.skills_matched)}")
    parts.append(f"workload: {rec.current_workload}")
    return " | ".join(parts)
