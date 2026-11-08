"""
business/user_service.py
-------------------------
Business logic for user management: registration, login, profile updates,
and admin user administration.

v2: Every meaningful operation now writes an AuditLog entry inside the
same database transaction, so audit records are always consistent with
the data they describe.
"""

import logging
from typing import Optional

from database.connection import get_db
from database.crud.user_crud import (
    authenticate_user,
    create_user,
    get_all_users,
    get_user_by_id,
    get_technicians,
    update_user_profile,
    change_password,
    admin_reset_password,
    set_user_active,
    update_last_login,
    count_users_by_role,
)
from database.crud.audit_crud import (
    log_login_success,
    log_login_failure,
    log_logout,
    log_user_created,
    log_user_deactivated,
    log_user_activated,
    log_password_reset,
    log_password_changed,
    log_event,
)
from database.models.user import UserRole
from core.security import (
    login_user,
    logout_user,
    get_current_user_id,
    validate_password_strength,
    sanitise_string,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def login(username: str, plain_password: str) -> dict:
    """
    Authenticate a user and populate the Streamlit session.

    Audit events written:
      - "user.login" outcome="success"  on successful login
      - "user.login" outcome="failure"  on bad credentials

    Returns
    -------
    dict with keys: success, error, user
    """
    if not username or not plain_password:
        return {"success": False, "error": "Username and password are required.", "user": None}

    with get_db() as session:
        user = authenticate_user(session, username.strip(), plain_password)

        if not user:
            # Audit the failed attempt (no user_id — unknown username)
            log_login_failure(session, username=username.strip())
            return {"success": False, "error": "Invalid username or password.", "user": None}

        if not user.is_active:
            log_event(
                session,
                action="user.login",
                user_id=user.id,
                entity_type="user",
                entity_id=user.id,
                detail={"reason": "account_inactive"},
                outcome="denied",
            )
            return {
                "success": False,
                "error": "Your account has been deactivated. Contact an administrator.",
                "user": None,
            }

        update_last_login(session, user.id)
        log_login_success(session, user_id=user.id)
        user_dict = user.to_dict()

    login_user(user_dict)
    logger.info(
        "Successful login: user_id=%s username=%r", user_dict["id"], user_dict["username"]
    )
    return {"success": True, "error": None, "user": user_dict}


def logout(user_id: Optional[int] = None) -> None:
    """
    Log out the current user, clear session state, and write an audit entry.
    """
    uid = user_id or get_current_user_id()
    if uid:
        try:
            with get_db() as session:
                log_logout(session, user_id=uid)
        except Exception as exc:
            logger.warning("Could not write logout audit entry: %s", exc)
    logout_user()


# ---------------------------------------------------------------------------
# Self-registration (requesters only)
# ---------------------------------------------------------------------------

def register_requester(
    username: str,
    email: str,
    full_name: str,
    plain_password: str,
    confirm_password: str,
    department: Optional[str] = None,
    phone: Optional[str] = None,
) -> dict:
    """
    Register a new Requester account.
    Audit event: "user.created" written in the same transaction.

    Returns
    -------
    dict with keys: success, errors, user_id
    """
    errors: list[str] = []

    username = sanitise_string(username, 64).lower()
    email = sanitise_string(email, 256).lower()
    full_name = sanitise_string(full_name, 128)

    if len(username) < 3:
        errors.append("Username must be at least 3 characters.")
    if len(username) > 64:
        errors.append("Username must not exceed 64 characters.")
    if not email or "@" not in email:
        errors.append("A valid email address is required.")
    if len(full_name) < 2:
        errors.append("Full name must be at least 2 characters.")

    if plain_password != confirm_password:
        errors.append("Passwords do not match.")
    else:
        strength_errors = validate_password_strength(plain_password)
        if strength_errors:
            errors.extend([f"Password must include: {e}" for e in strength_errors])

    if errors:
        return {"success": False, "errors": errors, "user_id": None}

    try:
        with get_db() as session:
            user = create_user(
                session=session,
                username=username,
                email=email,
                full_name=full_name,
                plain_password=plain_password,
                role=UserRole.REQUESTER,
                department=department,
                phone=phone,
            )
            log_user_created(
                session,
                actor_id=user.id,      # self-registration: actor = new user
                new_user_id=user.id,
                role=UserRole.REQUESTER.value,
            )
            user_id = user.id

        logger.info("New requester registered: user_id=%s username=%r", user_id, username)
        return {"success": True, "errors": [], "user_id": user_id}

    except ValueError as exc:
        return {"success": False, "errors": [str(exc)], "user_id": None}
    except Exception as exc:
        logger.error("Registration failed: %s", exc)
        return {
            "success": False,
            "errors": ["Registration failed. Please try again."],
            "user_id": None,
        }


# ---------------------------------------------------------------------------
# Admin: create any user role
# ---------------------------------------------------------------------------

def admin_create_user(
    username: str,
    email: str,
    full_name: str,
    plain_password: str,
    role: str,
    department: Optional[str] = None,
    phone: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> dict:
    """
    Admin creates a user with any role.
    Audit event: "user.created" with actor_id = admin who issued the command.

    Returns
    -------
    dict with keys: success, errors, user_id
    """
    errors: list[str] = []

    username = sanitise_string(username, 64).lower()
    email = sanitise_string(email, 256).lower()
    full_name = sanitise_string(full_name, 128)

    if len(username) < 3:
        errors.append("Username must be at least 3 characters.")
    if not email or "@" not in email:
        errors.append("A valid email address is required.")
    if len(full_name) < 2:
        errors.append("Full name must be at least 2 characters.")

    try:
        role_enum = UserRole(role)
    except ValueError:
        errors.append(
            f"Invalid role '{role}'. Must be one of: requester, technician, admin."
        )
        role_enum = UserRole.REQUESTER

    strength_errors = validate_password_strength(plain_password)
    if strength_errors:
        errors.extend([f"Password must include: {e}" for e in strength_errors])

    if errors:
        return {"success": False, "errors": errors, "user_id": None}

    try:
        with get_db() as session:
            user = create_user(
                session=session,
                username=username,
                email=email,
                full_name=full_name,
                plain_password=plain_password,
                role=role_enum,
                department=department,
                phone=phone,
            )
            log_user_created(
                session,
                actor_id=actor_id or user.id,
                new_user_id=user.id,
                role=role_enum.value,
            )
            user_id = user.id

        logger.info(
            "Admin created user: user_id=%s username=%r role=%s", user_id, username, role
        )
        return {"success": True, "errors": [], "user_id": user_id}

    except ValueError as exc:
        return {"success": False, "errors": [str(exc)], "user_id": None}
    except Exception as exc:
        logger.error("Admin user creation failed: %s", exc)
        return {
            "success": False,
            "errors": ["User creation failed. Please try again."],
            "user_id": None,
        }


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------

def update_own_profile(
    user_id: int,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    department: Optional[str] = None,
    phone: Optional[str] = None,
) -> dict:
    try:
        with get_db() as session:
            update_user_profile(
                session=session,
                user_id=user_id,
                full_name=full_name,
                email=email,
                department=department,
                phone=phone,
            )
            log_event(
                session,
                action="user.profile_updated",
                user_id=user_id,
                entity_type="user",
                entity_id=user_id,
            )
        return {"success": True, "error": None}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.error("Profile update failed for user_id=%s: %s", user_id, exc)
        return {"success": False, "error": "Profile update failed. Please try again."}


def change_own_password(
    user_id: int,
    current_password: str,
    new_password: str,
    confirm_new_password: str,
) -> dict:
    if new_password != confirm_new_password:
        return {"success": False, "error": "New passwords do not match."}

    strength_errors = validate_password_strength(new_password)
    if strength_errors:
        return {
            "success": False,
            "error": "Password requirements: " + "; ".join(strength_errors),
        }

    try:
        with get_db() as session:
            change_password(session, user_id, current_password, new_password)
            log_password_changed(session, user_id=user_id)
        return {"success": True, "error": None}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.error("Password change failed for user_id=%s: %s", user_id, exc)
        return {"success": False, "error": "Password change failed. Please try again."}


# ---------------------------------------------------------------------------
# Admin: user management
# ---------------------------------------------------------------------------

def admin_list_users(
    role: Optional[str] = None,
    active_only: bool = False,
) -> list[dict]:
    role_enum = UserRole(role) if role else None
    with get_db() as session:
        users = get_all_users(session, role=role_enum, active_only=active_only)
        return [u.to_dict() for u in users]


def admin_list_technicians() -> list[dict]:
    with get_db() as session:
        techs = get_technicians(session, active_only=True)
        return [t.to_dict() for t in techs]


def admin_toggle_user_active(
    user_id: int,
    active: bool,
    actor_id: Optional[int] = None,
) -> dict:
    try:
        with get_db() as session:
            set_user_active(session, user_id, active)
            if active:
                log_user_activated(session, actor_id=actor_id or user_id, target_user_id=user_id)
            else:
                log_user_deactivated(session, actor_id=actor_id or user_id, target_user_id=user_id)
        action = "activated" if active else "deactivated"
        logger.info("Admin %s user_id=%s", action, user_id)
        return {"success": True, "error": None}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}


def admin_do_reset_password(
    user_id: int,
    new_password: str,
    confirm_password: str,
    actor_id: Optional[int] = None,
) -> dict:
    if new_password != confirm_password:
        return {"success": False, "error": "Passwords do not match."}
    strength_errors = validate_password_strength(new_password)
    if strength_errors:
        return {
            "success": False,
            "error": "Password requirements: " + "; ".join(strength_errors),
        }
    try:
        with get_db() as session:
            admin_reset_password(session, user_id, new_password)
            log_password_reset(
                session,
                actor_id=actor_id or user_id,
                target_user_id=user_id,
            )
        return {"success": True, "error": None}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}


def get_user_role_counts() -> dict[str, int]:
    with get_db() as session:
        return count_users_by_role(session)
