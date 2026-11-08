"""
database/crud/user_crud.py
--------------------------
All database operations for the User model.
Every function accepts an open SQLAlchemy Session and returns
ORM objects or raises on error — no business logic lives here.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models.user import User, UserRole
from core.security import hash_password, verify_password

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_user_by_id(session: Session, user_id: int) -> Optional[User]:
    return session.get(User, user_id)


def get_user_by_username(session: Session, username: str) -> Optional[User]:
    stmt = select(User).where(User.username == username.strip().lower())
    return session.scalar(stmt)


def get_user_by_email(session: Session, email: str) -> Optional[User]:
    stmt = select(User).where(User.email == email.strip().lower())
    return session.scalar(stmt)


def get_all_users(
    session: Session,
    role: Optional[UserRole] = None,
    active_only: bool = True,
) -> list[User]:
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if active_only:
        stmt = stmt.where(User.is_active == True)  # noqa: E712
    stmt = stmt.order_by(User.full_name)
    return list(session.scalars(stmt).all())


def get_technicians(session: Session, active_only: bool = True) -> list[User]:
    return get_all_users(session, role=UserRole.TECHNICIAN, active_only=active_only)


def count_users_by_role(session: Session) -> dict[str, int]:
    """Return {role_value: count} for all roles."""
    stmt = (
        select(User.role, func.count(User.id))
        .where(User.is_active == True)  # noqa: E712
        .group_by(User.role)
    )
    rows = session.execute(stmt).all()
    return {row[0].value: row[1] for row in rows}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_user(
    session: Session,
    username: str,
    email: str,
    full_name: str,
    plain_password: str,
    role: UserRole = UserRole.REQUESTER,
    department: Optional[str] = None,
    phone: Optional[str] = None,
) -> User:
    """
    Create and persist a new user.
    Raises ValueError on duplicate username/email.
    Raises ValueError on weak password (delegated to hash_password).
    """
    username = username.strip().lower()
    email = email.strip().lower()

    # Check uniqueness before hitting the DB constraint for a cleaner error
    if get_user_by_username(session, username):
        raise ValueError(f"Username '{username}' is already taken.")
    if get_user_by_email(session, email):
        raise ValueError(f"Email '{email}' is already registered.")

    user = User(
        username=username,
        email=email,
        full_name=full_name.strip(),
        password_hash=hash_password(plain_password),
        role=role,
        department=department.strip() if department else None,
        phone=phone.strip() if phone else None,
        is_active=True,
    )
    session.add(user)
    try:
        session.flush()   # get the generated id without committing
    except IntegrityError as exc:
        session.rollback()
        logger.error("Integrity error creating user '%s': %s", username, exc)
        raise ValueError("A user with that username or email already exists.") from exc

    logger.info("Created user id=%s username=%r role=%s", user.id, username, role.value)
    return user


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_user_profile(
    session: Session,
    user_id: int,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    department: Optional[str] = None,
    phone: Optional[str] = None,
) -> User:
    user = get_user_by_id(session, user_id)
    if not user:
        raise ValueError(f"User id={user_id} not found.")

    if full_name is not None:
        user.full_name = full_name.strip()
    if email is not None:
        new_email = email.strip().lower()
        existing = get_user_by_email(session, new_email)
        if existing and existing.id != user_id:
            raise ValueError(f"Email '{new_email}' is already in use.")
        user.email = new_email
    if department is not None:
        user.department = department.strip() or None
    if phone is not None:
        user.phone = phone.strip() or None

    session.flush()
    logger.info("Updated profile for user id=%s", user_id)
    return user


def change_password(
    session: Session,
    user_id: int,
    current_plain: str,
    new_plain: str,
) -> None:
    """Verify current password then replace with new hash."""
    user = get_user_by_id(session, user_id)
    if not user:
        raise ValueError(f"User id={user_id} not found.")
    if not verify_password(current_plain, user.password_hash):
        raise ValueError("Current password is incorrect.")
    user.password_hash = hash_password(new_plain)
    session.flush()
    logger.info("Password changed for user id=%s", user_id)


def admin_reset_password(
    session: Session,
    user_id: int,
    new_plain: str,
) -> None:
    """Admin-only: reset any user's password without checking the old one."""
    user = get_user_by_id(session, user_id)
    if not user:
        raise ValueError(f"User id={user_id} not found.")
    user.password_hash = hash_password(new_plain)
    session.flush()
    logger.info("Admin reset password for user id=%s", user_id)


def set_user_active(session: Session, user_id: int, active: bool) -> User:
    user = get_user_by_id(session, user_id)
    if not user:
        raise ValueError(f"User id={user_id} not found.")
    user.is_active = active
    session.flush()
    logger.info("Set user id=%s is_active=%s", user_id, active)
    return user


def update_last_login(session: Session, user_id: int) -> None:
    user = get_user_by_id(session, user_id)
    if user:
        user.last_login_at = datetime.now(timezone.utc)
        session.flush()


# ---------------------------------------------------------------------------
# Authentication helper
# ---------------------------------------------------------------------------

def authenticate_user(
    session: Session, username: str, plain_password: str
) -> Optional[User]:
    """
    Validate credentials. Returns the User on success, None on failure.
    Intentionally gives the same error path for wrong username vs wrong
    password to avoid username enumeration.
    """
    user = get_user_by_username(session, username)
    if not user:
        # Perform a dummy hash check to maintain constant-time behaviour
        verify_password(plain_password, "$2b$12$invalidhashpadding000000000000000000000000000000000000000")
        return None
    if not user.is_active:
        return None
    if not verify_password(plain_password, user.password_hash):
        return None
    return user
