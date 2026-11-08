"""
database/models/__init__.py
---------------------------
Exports the shared declarative Base and ALL ORM model classes so that
`Base.metadata.create_all()` in connection.py discovers every table.

v2: Added Location, TechnicianSkill, RequestComment, RequestHistory, AuditLog.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ---- Original models -------------------------------------------------------
from database.models.user import User                        # noqa: E402, F401
from database.models.request import ServiceRequest          # noqa: E402, F401
from database.models.assignment import Assignment            # noqa: E402, F401
from database.models.status_history import StatusHistory    # noqa: E402, F401

# ---- v2 models -------------------------------------------------------------
from database.models.location import Location               # noqa: E402, F401
from database.models.technician_skill import TechnicianSkill  # noqa: E402, F401
from database.models.request_comment import RequestComment  # noqa: E402, F401
from database.models.request_history import RequestHistory  # noqa: E402, F401
from database.models.audit_log import AuditLog              # noqa: E402, F401

__all__ = [
    "Base",
    # original
    "User",
    "ServiceRequest",
    "Assignment",
    "StatusHistory",
    # v2
    "Location",
    "TechnicianSkill",
    "RequestComment",
    "RequestHistory",
    "AuditLog",
]
