"""
database/crud/request_crud.py
------------------------------
All database operations for the ServiceRequest model.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.orm import Session, joinedload

from database.models.request import (
    ServiceRequest,
    RequestCategory,
    RequestPriority,
    RequestStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reference number generation
# ---------------------------------------------------------------------------

def _next_reference_number(session: Session) -> str:
    """Generate the next REQ-NNNNN reference number atomically."""
    count = session.scalar(select(func.count(ServiceRequest.id))) or 0
    return f"REQ-{count + 1:05d}"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_request_by_id(
    session: Session,
    request_id: int,
    load_relations: bool = False,
) -> Optional[ServiceRequest]:
    if not load_relations:
        return session.get(ServiceRequest, request_id)
    stmt = (
        select(ServiceRequest)
        .options(
            joinedload(ServiceRequest.requester),
            joinedload(ServiceRequest.assignment),
            joinedload(ServiceRequest.status_history),
        )
        .where(ServiceRequest.id == request_id)
    )
    return session.scalar(stmt)


def get_request_by_reference(
    session: Session, reference_number: str
) -> Optional[ServiceRequest]:
    stmt = select(ServiceRequest).where(
        ServiceRequest.reference_number == reference_number.strip().upper()
    )
    return session.scalar(stmt)


def get_requests_for_requester(
    session: Session,
    requester_id: int,
    status_filter: Optional[list[RequestStatus]] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ServiceRequest]:
    stmt = (
        select(ServiceRequest)
        .where(ServiceRequest.requester_id == requester_id)
        .order_by(desc(ServiceRequest.created_at))
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        stmt = stmt.where(ServiceRequest.status.in_(status_filter))
    return list(session.scalars(stmt).all())


def get_requests_for_technician(
    session: Session,
    technician_id: int,
    status_filter: Optional[list[RequestStatus]] = None,
) -> list[ServiceRequest]:
    """Return requests assigned to a specific technician via the Assignment table."""
    from database.models.assignment import Assignment

    stmt = (
        select(ServiceRequest)
        .join(Assignment, Assignment.request_id == ServiceRequest.id)
        .where(Assignment.technician_id == technician_id)
        .order_by(
            # Critical and high priority first, then by creation date
            ServiceRequest.priority.desc(),
            desc(ServiceRequest.created_at),
        )
    )
    if status_filter:
        stmt = stmt.where(ServiceRequest.status.in_(status_filter))
    return list(session.scalars(stmt).all())


def get_all_requests(
    session: Session,
    status_filter: Optional[list[RequestStatus]] = None,
    category_filter: Optional[RequestCategory] = None,
    priority_filter: Optional[RequestPriority] = None,
    search_query: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[ServiceRequest]:
    stmt = (
        select(ServiceRequest)
        .order_by(desc(ServiceRequest.created_at))
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        stmt = stmt.where(ServiceRequest.status.in_(status_filter))
    if category_filter:
        stmt = stmt.where(ServiceRequest.category == category_filter)
    if priority_filter:
        stmt = stmt.where(ServiceRequest.priority == priority_filter)
    if search_query:
        q = f"%{search_query.strip()}%"
        stmt = stmt.where(
            or_(
                ServiceRequest.title.ilike(q),
                ServiceRequest.description.ilike(q),
                ServiceRequest.reference_number.ilike(q),
                ServiceRequest.location.ilike(q),
            )
        )
    return list(session.scalars(stmt).all())


def get_open_requests_with_embeddings(
    session: Session,
) -> list[ServiceRequest]:
    """Return all active (non-terminal) requests that have an embedding stored."""
    stmt = select(ServiceRequest).where(
        and_(
            ServiceRequest.embedding_str != None,  # noqa: E711
            ServiceRequest.status.in_([
                RequestStatus.SUBMITTED,
                RequestStatus.OPEN,
                RequestStatus.ASSIGNED,
                RequestStatus.IN_PROGRESS,
                RequestStatus.ON_HOLD,
            ]),
        )
    )
    return list(session.scalars(stmt).all())


def count_requests_by_status(session: Session) -> dict[str, int]:
    stmt = (
        select(ServiceRequest.status, func.count(ServiceRequest.id))
        .group_by(ServiceRequest.status)
    )
    return {row[0].value: row[1] for row in session.execute(stmt).all()}


def count_requests_by_category(session: Session) -> dict[str, int]:
    stmt = (
        select(ServiceRequest.category, func.count(ServiceRequest.id))
        .group_by(ServiceRequest.category)
    )
    return {row[0].value: row[1] for row in session.execute(stmt).all()}


def count_requests_by_priority(session: Session) -> dict[str, int]:
    stmt = (
        select(ServiceRequest.priority, func.count(ServiceRequest.id))
        .group_by(ServiceRequest.priority)
    )
    return {row[0].value: row[1] for row in session.execute(stmt).all()}


def get_requests_dataframe_raw(session: Session) -> list[dict]:
    """
    Return all requests as a list of dicts for Pandas consumption.
    Includes joined technician name from the assignment table.
    """
    from database.models.assignment import Assignment
    from database.models.user import User

    stmt = (
        select(
            ServiceRequest.id,
            ServiceRequest.reference_number,
            ServiceRequest.title,
            ServiceRequest.category,
            ServiceRequest.priority,
            ServiceRequest.status,
            ServiceRequest.location,
            ServiceRequest.created_at,
            ServiceRequest.resolved_at,
            ServiceRequest.requester_id,
            User.full_name.label("technician_name"),
        )
        .outerjoin(Assignment, Assignment.request_id == ServiceRequest.id)
        .outerjoin(User, User.id == Assignment.technician_id)
        .order_by(desc(ServiceRequest.created_at))
    )
    rows = session.execute(stmt).all()
    return [row._asdict() for row in rows]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_request(
    session: Session,
    requester_id: int,
    title: str,
    description: str,
    location: str,
    category: RequestCategory = RequestCategory.OTHER,
    priority: RequestPriority = RequestPriority.MEDIUM,
    building: Optional[str] = None,
    floor_or_room: Optional[str] = None,
    sub_category: Optional[str] = None,
    department_target: Optional[str] = None,
) -> ServiceRequest:
    ref = _next_reference_number(session)

    req = ServiceRequest(
        reference_number=ref,
        requester_id=requester_id,
        title=title.strip(),
        description=description.strip(),
        location=location.strip(),
        category=category,
        priority=priority,
        building=building.strip() if building else None,
        floor_or_room=floor_or_room.strip() if floor_or_room else None,
        sub_category=sub_category.strip() if sub_category else None,
        department_target=department_target.strip() if department_target else None,
        status=RequestStatus.SUBMITTED,
    )
    session.add(req)
    session.flush()
    logger.info(
        "Created request ref=%s id=%s by requester_id=%s",
        ref, req.id, requester_id,
    )
    return req


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_request_status(
    session: Session,
    request_id: int,
    new_status: RequestStatus,
    changed_by_id: int,
    changed_by_role: str,
    note: Optional[str] = None,
) -> ServiceRequest:
    """
    Update request status and automatically create a StatusHistory record.
    Returns the updated request.
    """
    from database.crud.history_crud import create_history_entry

    req = get_request_by_id(session, request_id)
    if not req:
        raise ValueError(f"Request id={request_id} not found.")

    previous_status = req.status
    req.status = new_status

    now = datetime.now(timezone.utc)
    if new_status == RequestStatus.RESOLVED and not req.resolved_at:
        req.resolved_at = now
    if new_status == RequestStatus.CLOSED and not req.closed_at:
        req.closed_at = now

    create_history_entry(
        session=session,
        request_id=request_id,
        changed_by_id=changed_by_id,
        changed_by_role=changed_by_role,
        previous_status=previous_status,
        new_status=new_status,
        note=note,
    )
    session.flush()
    logger.info(
        "Request id=%s status: %s → %s by user id=%s",
        request_id, previous_status.value, new_status.value, changed_by_id,
    )
    return req


def update_request_ai_fields(
    session: Session,
    request_id: int,
    ai_suggested_category: Optional[str] = None,
    ai_suggested_priority: Optional[str] = None,
    ai_classification_notes: Optional[str] = None,
    ai_confidence_score: Optional[float] = None,
    embedding_str: Optional[str] = None,
) -> ServiceRequest:
    req = get_request_by_id(session, request_id)
    if not req:
        raise ValueError(f"Request id={request_id} not found.")
    if ai_suggested_category is not None:
        req.ai_suggested_category = ai_suggested_category
    if ai_suggested_priority is not None:
        req.ai_suggested_priority = ai_suggested_priority
    if ai_classification_notes is not None:
        req.ai_classification_notes = ai_classification_notes
    if ai_confidence_score is not None:
        req.ai_confidence_score = ai_confidence_score
    if embedding_str is not None:
        req.embedding_str = embedding_str
    session.flush()
    return req


def update_request_priority(
    session: Session,
    request_id: int,
    new_priority: RequestPriority,
    changed_by_id: int,
) -> ServiceRequest:
    req = get_request_by_id(session, request_id)
    if not req:
        raise ValueError(f"Request id={request_id} not found.")
    req.priority = new_priority
    session.flush()
    logger.info(
        "Request id=%s priority set to %s by user id=%s",
        request_id, new_priority.value, changed_by_id,
    )
    return req


def update_resolution_notes(
    session: Session,
    request_id: int,
    resolution_notes: str,
) -> ServiceRequest:
    req = get_request_by_id(session, request_id)
    if not req:
        raise ValueError(f"Request id={request_id} not found.")
    req.resolution_notes = resolution_notes.strip()
    session.flush()
    return req


# ---------------------------------------------------------------------------
# v2 extensions
# ---------------------------------------------------------------------------

def update_request_v2_fields(
    session: Session,
    request_id: int,
    location_id: Optional[int] = None,
    due_date=None,
    ai_summary: Optional[str] = None,
    ai_recommendation: Optional[str] = None,
    assigned_technician_id: Optional[int] = None,
) -> ServiceRequest:
    """
    Update any combination of the v2 extended fields on a ServiceRequest.
    Passing None for a field leaves it unchanged.
    Passing the sentinel value _CLEAR (an empty string sentinel) clears the field.
    """
    req = get_request_by_id(session, request_id)
    if not req:
        raise ValueError(f"Request id={request_id} not found.")

    if location_id is not None:
        req.location_id = location_id
    if due_date is not None:
        req.due_date = due_date
    if ai_summary is not None:
        req.ai_summary = ai_summary.strip() or None
    if ai_recommendation is not None:
        req.ai_recommendation = ai_recommendation.strip() or None
    if assigned_technician_id is not None:
        req.assigned_technician_id = assigned_technician_id

    session.flush()
    return req


def clear_assigned_technician(session: Session, request_id: int) -> ServiceRequest:
    """Zero out the denormalised assigned_technician_id field."""
    req = get_request_by_id(session, request_id)
    if not req:
        raise ValueError(f"Request id={request_id} not found.")
    req.assigned_technician_id = None
    session.flush()
    return req


def write_request_history(
    session: Session,
    request_id: int,
    changed_by: int,
    event_type,           # HistoryEventType enum value
    old_status: Optional[str] = None,
    new_status: Optional[str] = None,
    field_name: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    note: Optional[str] = None,
):
    """
    Append an entry to the request_history table.
    Imported lazily to avoid circular imports.
    """
    from database.models.request_history import RequestHistory

    entry = RequestHistory(
        request_id=request_id,
        changed_by=changed_by,
        event_type=event_type,
        old_status=old_status,
        new_status=new_status,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        note=note.strip() if note else None,
    )
    session.add(entry)
    session.flush()
    return entry


def get_requests_due_before(
    session: Session,
    deadline,           # datetime
    status_filter: Optional[list] = None,
) -> list[ServiceRequest]:
    """Return requests whose due_date is before the given datetime."""
    from sqlalchemy import and_

    stmt = (
        select(ServiceRequest)
        .where(
            ServiceRequest.due_date != None,  # noqa: E711
            ServiceRequest.due_date <= deadline,
        )
        .order_by(ServiceRequest.due_date.asc())
    )
    if status_filter:
        stmt = stmt.where(ServiceRequest.status.in_(status_filter))
    return list(session.scalars(stmt).all())
