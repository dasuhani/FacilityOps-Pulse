"""
database/crud/comment_crud.py
--------------------------------
All database operations for the RequestComment model.
Comments are append-only — no update or delete operations.
"""

import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session, joinedload

from database.models.request_comment import RequestComment

logger = logging.getLogger(__name__)

# Maximum comment length enforced at the application layer
COMMENT_MAX_LEN = 4000


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_comments_for_request(
    session: Session,
    request_id: int,
    load_user: bool = True,
) -> list[RequestComment]:
    """Return all comments for a request, oldest first."""
    stmt = (
        select(RequestComment)
        .where(RequestComment.request_id == request_id)
        .order_by(RequestComment.created_at.asc())
    )
    if load_user:
        stmt = stmt.options(joinedload(RequestComment.user))
    return list(session.scalars(stmt).all())


def get_comment_by_id(
    session: Session, comment_id: int
) -> Optional[RequestComment]:
    return session.get(RequestComment, comment_id)


def count_comments_for_request(session: Session, request_id: int) -> int:
    stmt = (
        select(func.count(RequestComment.id))
        .where(RequestComment.request_id == request_id)
    )
    return session.scalar(stmt) or 0


def get_recent_comments(
    session: Session,
    limit: int = 20,
    user_id: Optional[int] = None,
) -> list[RequestComment]:
    """Return the most recent comments, optionally filtered to one user."""
    stmt = (
        select(RequestComment)
        .order_by(RequestComment.created_at.desc())
        .limit(limit)
    )
    if user_id is not None:
        stmt = stmt.where(RequestComment.user_id == user_id)
    return list(session.scalars(stmt).all())


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def add_comment(
    session: Session,
    request_id: int,
    user_id: int,
    comment: str,
) -> RequestComment:
    """
    Append a comment to a service request.

    Raises
    ------
    ValueError
        If the comment is empty or exceeds COMMENT_MAX_LEN characters.
    """
    comment = comment.strip()
    if not comment:
        raise ValueError("Comment must not be empty.")
    if len(comment) > COMMENT_MAX_LEN:
        raise ValueError(
            f"Comment exceeds the maximum length of {COMMENT_MAX_LEN} characters."
        )

    obj = RequestComment(
        request_id=request_id,
        user_id=user_id,
        comment=comment,
    )
    session.add(obj)
    session.flush()
    logger.info(
        "Comment id=%s added to request id=%s by user id=%s",
        obj.id, request_id, user_id,
    )
    return obj
