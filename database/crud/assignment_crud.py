"""
database/crud/assignment_crud.py
---------------------------------
Database operations for the Assignment model.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from database.models.assignment import Assignment
from database.models.request import RequestStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_assignment_by_request(
    session: Session, request_id: int
) -> Optional[Assignment]:
    stmt = select(Assignment).where(Assignment.request_id == request_id)
    return session.scalar(stmt)


def get_assignments_for_technician(
    session: Session, technician_id: int
) -> list[Assignment]:
    stmt = (
        select(Assignment)
        .where(Assignment.technician_id == technician_id)
        .order_by(Assignment.assigned_at.desc())
    )
    return list(session.scalars(stmt).all())


def get_technician_open_workload(session: Session) -> dict[int, int]:
    """
    Return {technician_id: count_of_open_assigned_requests}.
    Used by admin to see current load before assigning.
    """
    from database.models.request import ServiceRequest

    stmt = (
        select(Assignment.technician_id, func.count(Assignment.id))
        .join(ServiceRequest, ServiceRequest.id == Assignment.request_id)
        .where(
            ServiceRequest.status.in_([
                RequestStatus.SUBMITTED,
                RequestStatus.OPEN,
                RequestStatus.ASSIGNED,
                RequestStatus.IN_PROGRESS,
                RequestStatus.ON_HOLD,
            ])
        )
        .group_by(Assignment.technician_id)
    )
    return {row[0]: row[1] for row in session.execute(stmt).all()}


# ---------------------------------------------------------------------------
# Create / Update
# ---------------------------------------------------------------------------

def assign_request(
    session: Session,
    request_id: int,
    technician_id: int,
    assigned_by_id: int,
    assignment_notes: Optional[str] = None,
    estimated_completion: Optional[datetime] = None,
) -> Assignment:
    """
    Assign (or re-assign) a request to a technician.
    If an assignment already exists, it is updated in place.
    Also transitions the request status to IN_PROGRESS if it is OPEN.
    Keeps the denormalised ServiceRequest.assigned_technician_id in sync (v2).
    """
    from database.models.request import ServiceRequest, RequestStatus
    from database.crud.request_crud import update_request_status

    existing = get_assignment_by_request(session, request_id)

    if existing:
        # Re-assignment: update technician and notes
        old_tech_id = existing.technician_id
        existing.technician_id = technician_id
        existing.assigned_by_id = assigned_by_id
        existing.assignment_notes = assignment_notes
        existing.estimated_completion = estimated_completion
        session.flush()
        logger.info(
            "Re-assigned request id=%s from technician id=%s to id=%s",
            request_id, old_tech_id, technician_id,
        )
        assignment = existing
    else:
        assignment = Assignment(
            request_id=request_id,
            technician_id=technician_id,
            assigned_by_id=assigned_by_id,
            assignment_notes=assignment_notes,
            estimated_completion=estimated_completion,
        )
        session.add(assignment)
        session.flush()
        logger.info(
            "Assigned request id=%s to technician id=%s by admin id=%s",
            request_id, technician_id, assigned_by_id,
        )

    # Sync denormalised field (v2)
    req = session.get(ServiceRequest, request_id)
    if req:
        req.assigned_technician_id = technician_id
        session.flush()

    # Move request to ASSIGNED if currently SUBMITTED or legacy OPEN
    req = session.get(ServiceRequest, request_id)
    if req and req.status in (RequestStatus.SUBMITTED, RequestStatus.OPEN):
        update_request_status(
            session=session,
            request_id=request_id,
            new_status=RequestStatus.ASSIGNED,
            changed_by_id=assigned_by_id,
            changed_by_role="admin",
            note=f"Request assigned to technician id={technician_id}.",
        )

    return assignment


def unassign_request(
    session: Session,
    request_id: int,
    unassigned_by_id: int,
) -> None:
    """Remove an assignment. Request is moved back to OPEN.
    Clears the denormalised assigned_technician_id field (v2)."""
    from database.crud.request_crud import update_request_status, clear_assigned_technician
    from database.models.request import RequestStatus

    assignment = get_assignment_by_request(session, request_id)
    if not assignment:
        logger.warning("Tried to unassign request id=%s — no assignment found.", request_id)
        return

    session.delete(assignment)
    session.flush()

    # Clear denormalised field (v2)
    clear_assigned_technician(session, request_id)

    update_request_status(
        session=session,
        request_id=request_id,
        new_status=RequestStatus.SUBMITTED,
        changed_by_id=unassigned_by_id,
        changed_by_role="admin",
        note="Assignment removed — request returned to submitted queue.",
    )
    logger.info("Unassigned request id=%s by user id=%s", request_id, unassigned_by_id)
