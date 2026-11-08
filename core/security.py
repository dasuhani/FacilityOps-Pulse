"""
core/security.py
----------------
Password hashing and Streamlit session-state authentication helpers.

Password hashing:
    Uses bcrypt with a cost factor of 12.
    NEVER store or log plain-text passwords.

Session helpers:
    Streamlit has no built-in server-side session store.
    We store a minimal auth context in st.session_state under a
    namespaced key so it doesn't conflict with page-level state.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import bcrypt
import streamlit as st

logger = logging.getLogger(__name__)

# Key used in st.session_state to hold the authenticated user context
_SESSION_KEY = "_facilityops_auth"


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(plain_text: str) -> str:
    """
    Hash a plain-text password with bcrypt (cost=12).

    Returns a UTF-8 string suitable for storing in the database.
    Raises ValueError if the password is empty.
    """
    if not plain_text or not plain_text.strip():
        raise ValueError("Password must not be empty.")
    if len(plain_text) > 72:
        # bcrypt silently truncates at 72 bytes — inform the caller
        raise ValueError("Password must be 72 characters or fewer.")

    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(plain_text.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_text: str, hashed: str) -> bool:
    """
    Verify a plain-text password against a stored bcrypt hash.
    Returns True if they match, False otherwise.
    Never raises on bad input — logs a warning instead.
    """
    if not plain_text or not hashed:
        return False
    try:
        return bcrypt.checkpw(
            plain_text.encode("utf-8"),
            hashed.encode("utf-8"),
        )
    except Exception as exc:
        logger.warning("Password verification error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

def _get_auth() -> dict:
    """Return the current auth dict from session state (may be empty)."""
    return st.session_state.get(_SESSION_KEY, {})


def login_user(user_dict: dict) -> None:
    """
    Store authenticated user information in session state.

    Parameters
    ----------
    user_dict : dict
        Must contain at minimum: id, username, role, full_name.
        Produced by User.to_dict() — never pass raw ORM objects to avoid
        SQLAlchemy DetachedInstanceError across requests.
    """
    required = {"id", "username", "role", "full_name"}
    missing = required - user_dict.keys()
    if missing:
        raise ValueError(f"user_dict is missing required keys: {missing}")

    st.session_state[_SESSION_KEY] = {
        **user_dict,
        "logged_in": True,
        "login_time": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(
        "User logged in: id=%s username=%r role=%s",
        user_dict["id"],
        user_dict["username"],
        user_dict["role"],
    )


def logout_user() -> None:
    """Clear the auth context from session state."""
    user = _get_auth()
    if user:
        logger.info(
            "User logged out: id=%s username=%r",
            user.get("id"),
            user.get("username"),
        )
    st.session_state.pop(_SESSION_KEY, None)


def is_authenticated() -> bool:
    """Return True if a user is currently logged in."""
    return _get_auth().get("logged_in", False) is True


def get_current_user() -> Optional[dict]:
    """
    Return the current user dict or None if not authenticated.
    Use this in every page to guard access.
    """
    auth = _get_auth()
    if auth.get("logged_in"):
        return auth
    return None


def get_current_user_id() -> Optional[int]:
    user = get_current_user()
    return user["id"] if user else None


def get_current_role() -> Optional[str]:
    user = get_current_user()
    return user["role"] if user else None


def require_role(*allowed_roles: str) -> dict:
    """
    Enforce role-based access control on a Streamlit page.

    Call at the top of any page module:
        user = require_role("admin", "technician")

    Stops page rendering with st.error + st.stop() if the user is not
    authenticated or does not have one of the allowed roles.
    """
    user = get_current_user()

    if not user:
        st.error("🔒 You must be logged in to access this page.")
        st.stop()

    if user["role"] not in allowed_roles:
        st.error(
            f"⛔ Access denied. This page requires one of these roles: "
            f"{', '.join(r.title() for r in allowed_roles)}. "
            f"Your role is: **{user['role'].title()}**."
        )
        st.stop()

    return user


# ---------------------------------------------------------------------------
# Input validation helpers (used across forms)
# ---------------------------------------------------------------------------

def validate_password_strength(password: str) -> list[str]:
    """
    Return a list of unmet password requirements.
    Empty list means the password passes all checks.
    """
    errors: list[str] = []
    if len(password) < 8:
        errors.append("At least 8 characters")
    if not any(c.isupper() for c in password):
        errors.append("At least one uppercase letter")
    if not any(c.islower() for c in password):
        errors.append("At least one lowercase letter")
    if not any(c.isdigit() for c in password):
        errors.append("At least one digit")
    if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in password):
        errors.append("At least one special character")
    return errors


def sanitise_string(value: str, max_length: int = 256) -> str:
    """
    Strip leading/trailing whitespace and truncate to max_length.
    Used before storing user-submitted text fields.
    """
    return value.strip()[:max_length] if value else ""
