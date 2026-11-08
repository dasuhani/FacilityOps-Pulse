"""
database/crud/history_crud.py
------------------------------
Database operations for the StatusHistory (audit log) model.
History records are immutable — never updated or deleted.
"""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.status_history import StatusHistory
from database.models.request import RequestStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_history_for_request(
    session: Session, request_id: int
) -> list[StatusHistory]:
    """Return all history entries for a request, oldest first."""
    stmt = (
        select(StatusHistory)
        .where(StatusHistory.request_id == request_id)
        .order_by(StatusHistory.changed_at.asc())
    )
    return list(session.scalars(stmt).all())


def get_latest_history_entry(
    session: Session, request_id: int
) -> Optional[StatusHistory]:
    stmt = (
        select(StatusHistory)
        .where(StatusHistory.request_id == request_id)
        .order_by(StatusHistory.changed_at.desc())
        .limit(1)
    )
    return session.scalar(stmt)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_history_entry(
    session: Session,
    request_id: int,
    changed_by_id: int,
    changed_by_role: str,
    new_status: RequestStatus,
    previous_status: Optional[RequestStatus] = None,
    note: Optional[str] = None,
) -> StatusHistory:
    """
    Append an immutable audit entry.
    Called automatically from request_crud.update_request_status —
    generally not called directly from application code.
    """
    entry = StatusHistory(
        request_id=request_id,
        changed_by_id=changed_by_id,
        changed_by_role=changed_by_role,
        previous_status=previous_status,
        new_status=new_status,
        note=note.strip() if note else None,
    )
    session.add(entry)
    session.flush()
    logger.debug(
        "History: request_id=%s %r → %r by user id=%s",
        request_id,
        previous_status.value if previous_status else "None",
        new_status.value,
        changed_by_id,
    )
    return entry


def record_request_created(
    session: Session,
    request_id: int,
    created_by_id: int,
    created_by_role: str,
) -> StatusHistory:
    """
    Insert the initial 'created' history entry when a new request is submitted.
    previous_status is NULL on creation events.
    """
    return create_history_entry(
        session=session,
        request_id=request_id,
        changed_by_id=created_by_id,
        changed_by_role=created_by_role,
        previous_status=None,
        new_status=RequestStatus.SUBMITTED,
        note="Request submitted.",
    )
