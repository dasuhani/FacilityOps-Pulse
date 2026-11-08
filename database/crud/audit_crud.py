"""
database/crud/audit_crud.py
-----------------------------
All database operations for the AuditLog model.
Audit records are immutable — read and append only.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from database.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_audit_log(
    session: Session,
    limit: int = 200,
    offset: int = 0,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    outcome: Optional[str] = None,
    since_hours: Optional[int] = None,
) -> list[AuditLog]:
    """
    Return audit log entries with optional filters.

    Parameters
    ----------
    since_hours : int | None
        If set, only return entries from the last N hours.
    """
    stmt = (
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action.strip()}%"))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if outcome:
        stmt = stmt.where(AuditLog.outcome == outcome)
    if since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        stmt = stmt.where(AuditLog.created_at >= cutoff)
    return list(session.scalars(stmt).all())


def get_audit_for_entity(
    session: Session,
    entity_type: str,
    entity_id: int,
) -> list[AuditLog]:
    """Return all audit entries for a specific entity (e.g. a user or request)."""
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id,
        )
        .order_by(AuditLog.created_at.asc())
    )
    return list(session.scalars(stmt).all())


def count_audit_events(
    session: Session,
    action: Optional[str] = None,
    outcome: Optional[str] = None,
    since_hours: Optional[int] = None,
) -> int:
    stmt = select(func.count(AuditLog.id))
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if outcome:
        stmt = stmt.where(AuditLog.outcome == outcome)
    if since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        stmt = stmt.where(AuditLog.created_at >= cutoff)
    return session.scalar(stmt) or 0


def count_failed_logins(
    session: Session, user_id: int, since_hours: int = 1
) -> int:
    """Count recent failed login attempts for a specific user — for brute-force detection."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    stmt = (
        select(func.count(AuditLog.id))
        .where(
            AuditLog.user_id == user_id,
            AuditLog.action == "user.login",
            AuditLog.outcome == "failure",
            AuditLog.created_at >= cutoff,
        )
    )
    return session.scalar(stmt) or 0


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def log_event(
    session: Session,
    action: str,
    user_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    detail: Optional[dict | str] = None,
    outcome: str = "success",
) -> AuditLog:
    """
    Append an immutable audit event.

    Parameters
    ----------
    action : str
        Dot-namespaced action identifier, e.g. "user.login", "request.created",
        "user.password_reset", "assignment.created".
    detail : dict | str | None
        Extra context.  Dicts are JSON-serialised automatically.
    outcome : str
        One of "success", "failure", "denied".
    """
    if isinstance(detail, dict):
        try:
            detail_str = json.dumps(detail, default=str)
        except Exception:
            detail_str = str(detail)
    elif detail is not None:
        detail_str = str(detail)
    else:
        detail_str = None

    entry = AuditLog(
        user_id=user_id,
        action=action.strip()[:64],
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail_str,
        outcome=outcome,
    )
    session.add(entry)
    # Use flush() not commit() — caller controls the transaction
    session.flush()
    logger.debug(
        "Audit: action=%r user_id=%s entity=%s/%s outcome=%s",
        action, user_id, entity_type, entity_id, outcome,
    )
    return entry


# ---------------------------------------------------------------------------
# Convenience wrappers for common events
# ---------------------------------------------------------------------------

def log_login_success(session: Session, user_id: int) -> AuditLog:
    return log_event(session, "user.login", user_id=user_id,
                     entity_type="user", entity_id=user_id, outcome="success")


def log_login_failure(session: Session, username: str) -> AuditLog:
    return log_event(session, "user.login", user_id=None,
                     detail={"username": username}, outcome="failure")


def log_logout(session: Session, user_id: int) -> AuditLog:
    return log_event(session, "user.logout", user_id=user_id,
                     entity_type="user", entity_id=user_id)


def log_user_created(session: Session, actor_id: int, new_user_id: int, role: str) -> AuditLog:
    return log_event(session, "user.created", user_id=actor_id,
                     entity_type="user", entity_id=new_user_id,
                     detail={"role": role})


def log_user_deactivated(session: Session, actor_id: int, target_user_id: int) -> AuditLog:
    return log_event(session, "user.deactivated", user_id=actor_id,
                     entity_type="user", entity_id=target_user_id)


def log_user_activated(session: Session, actor_id: int, target_user_id: int) -> AuditLog:
    return log_event(session, "user.activated", user_id=actor_id,
                     entity_type="user", entity_id=target_user_id)


def log_password_reset(session: Session, actor_id: int, target_user_id: int) -> AuditLog:
    return log_event(session, "user.password_reset", user_id=actor_id,
                     entity_type="user", entity_id=target_user_id)


def log_password_changed(session: Session, user_id: int) -> AuditLog:
    return log_event(session, "user.password_changed", user_id=user_id,
                     entity_type="user", entity_id=user_id)


def log_request_created(session: Session, user_id: int, request_id: int) -> AuditLog:
    return log_event(session, "request.created", user_id=user_id,
                     entity_type="request", entity_id=request_id)


def log_request_status_changed(
    session: Session, user_id: int, request_id: int,
    old_status: str, new_status: str
) -> AuditLog:
    return log_event(session, "request.status_changed", user_id=user_id,
                     entity_type="request", entity_id=request_id,
                     detail={"old": old_status, "new": new_status})


def log_request_assigned(
    session: Session, admin_id: int, request_id: int, technician_id: int
) -> AuditLog:
    return log_event(session, "request.assigned", user_id=admin_id,
                     entity_type="request", entity_id=request_id,
                     detail={"technician_id": technician_id})


def log_request_cancelled(session: Session, user_id: int, request_id: int) -> AuditLog:
    return log_event(session, "request.cancelled", user_id=user_id,
                     entity_type="request", entity_id=request_id)
