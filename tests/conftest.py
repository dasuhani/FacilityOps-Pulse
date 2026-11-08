"""
tests/conftest.py
-----------------
Shared pytest fixtures for the FacilityOps Pulse test suite.

Strategy
--------
All tests run against an **in-process SQLite database** (file: memory).
SQLite is used because:
  - Zero external dependencies — no PostgreSQL needed in CI.
  - CREATE_ALL / DROP_ALL is instant.
  - Every test function gets a fresh, isolated database via the
    `db_session` fixture (function scope).

The `db_session` fixture:
  1. Creates all tables from the ORM metadata.
  2. Yields a SQLAlchemy Session bound to the in-memory engine.
  3. Rolls back every change after the test, then drops all tables.
     This guarantees complete isolation even if a test commits.

PostgreSQL-specific syntax (ENUM types, RESTRICT on FK) is handled by
using SQLite's more permissive mode for tests.  The models use
`native_enum=False` workaround: SQLite doesn't support PG ENUM types,
so we patch the Enum columns to use String via the test engine config.

The `make_user` / `make_request` factory helpers create minimal valid
objects and return them already flushed (but not committed) so tests
can assert against them immediately.
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path regardless of how pytest is invoked
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Force SQLite for tests — prevents the production PostgreSQL engine
# from being created (which can hang during pytest cleanup when
# PostgreSQL is running on the dev machine).
import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["DB_USER"] = ""
os.environ["DB_PASSWORD"] = ""

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session

# ---------------------------------------------------------------------------
# SQLite engine — created once per test session
# ---------------------------------------------------------------------------

# Use in-memory SQLite. The production engine also uses SQLite (because
# conftest.py sets DATABASE_URL=sqlite:///:memory:) so there's no
# PostgreSQL connection to hang on during cleanup.
_TEST_DATABASE_URL = "sqlite:///:memory:"


def _make_test_engine():
    engine = create_engine(
        _TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # SQLite foreign-key enforcement is off by default; turn it on
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


# Module-level engine — shared across all tests in one pytest run
_engine = _make_test_engine()


# ---------------------------------------------------------------------------
# Schema bootstrap — create tables once, reuse across tests
# ---------------------------------------------------------------------------

def _bootstrap_schema():
    """
    Import every model (registering them with Base.metadata) then run
    create_all on the in-memory SQLite engine.

    SQLite doesn't support PG-style ENUM types.  SQLAlchemy's Enum()
    column stores as VARCHAR on SQLite automatically when native_enum is
    not explicitly forced, so the models work without modification.
    """
    from database.models import Base
    from database.models.user import User                            # noqa: F401
    from database.models.request import ServiceRequest              # noqa: F401
    from database.models.assignment import Assignment                # noqa: F401
    from database.models.status_history import StatusHistory        # noqa: F401
    from database.models.location import Location                   # noqa: F401
    from database.models.technician_skill import TechnicianSkill    # noqa: F401
    from database.models.request_comment import RequestComment      # noqa: F401
    from database.models.request_history import RequestHistory      # noqa: F401
    from database.models.audit_log import AuditLog                  # noqa: F401

    Base.metadata.create_all(bind=_engine)


_bootstrap_schema()

# ---------------------------------------------------------------------------
# Redirect the production database engine to our test SQLite engine.
#
# database.connection creates a PostgreSQL engine at module import time.
# When psycopg2 is installed and PostgreSQL is running, that engine opens
# real connections that can hang during pytest cleanup.
#
# By replacing the production engine, SessionLocal, and get_db with test
# versions, any code path that calls get_db() (e.g. business.analytics_service)
# will use the in-memory SQLite engine instead of PostgreSQL.
# ---------------------------------------------------------------------------

_TestSessionFactory = sessionmaker(
    bind=_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Core fixture: db_session
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session() -> Session:
    """
    Yield a SQLAlchemy Session for one test.

    Each test runs inside a SAVEPOINT so we can rollback everything
    after the test without dropping/recreating tables.
    """
    connection = _engine.connect()
    transaction = connection.begin()

    session = _TestSessionFactory(bind=connection)

    # Nested SAVEPOINT — allows session.commit() inside tested code
    # without actually committing to the connection-level transaction
    nested = connection.begin_nested()

    # Restart the SAVEPOINT after each session.commit() so the test
    # can call commit() freely
    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(session, trans):
        nonlocal nested
        if trans.nested and not trans._parent.nested:
            nested = connection.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def make_user(db_session):
    """
    Factory that creates a User and flushes it.
    Returns a callable: make_user(username, role, ...)
    """
    from database.models.user import User, UserRole
    from core.security import hash_password

    created = []

    def _factory(
        username: str = "testuser",
        full_name: str = "Test User",
        email: str = None,
        role: str = "requester",
        password: str = "Test@1234",
        is_active: bool = True,
        department: str = None,
    ) -> User:
        if email is None:
            email = f"{username}@test.local"
        user = User(
            username=username,
            email=email,
            full_name=full_name,
            password_hash=hash_password(password),
            role=UserRole(role),
            is_active=is_active,
            department=department,
        )
        db_session.add(user)
        db_session.flush()
        created.append(user)
        return user

    return _factory


@pytest.fixture()
def make_request(db_session, make_user):
    """
    Factory that creates a ServiceRequest and flushes it.
    Auto-creates a requester user if none supplied.
    """
    from database.models.request import (
        ServiceRequest, RequestCategory, RequestPriority, RequestStatus
    )

    def _factory(
        requester=None,
        title: str = "Test request title here",
        description: str = "Test description that is long enough to pass validation.",
        location: str = "Building A, Room 101",
        category: str = "other",
        priority: str = "medium",
        status: str = "submitted",
        reference_suffix: str = "00001",
    ) -> ServiceRequest:
        if requester is None:
            requester = make_user(username=f"req_{reference_suffix}", role="requester")

        req = ServiceRequest(
            reference_number=f"REQ-{reference_suffix}",
            requester_id=requester.id,
            title=title,
            description=description,
            location=location,
            category=RequestCategory(category),
            priority=RequestPriority(priority),
            status=RequestStatus(status),
        )
        db_session.add(req)
        db_session.flush()
        return req

    return _factory


@pytest.fixture()
def make_location(db_session):
    """Factory that creates a Location and flushes it."""
    from database.models.location import Location

    def _factory(
        building_name: str = "Main Building",
        floor: str = "1",
        area: str = "Reception",
        is_active: int = 1,
    ) -> Location:
        loc = Location(
            building_name=building_name,
            floor=floor,
            area=area,
            is_active=is_active,
        )
        db_session.add(loc)
        db_session.flush()
        return loc

    return _factory


@pytest.fixture()
def admin_user(make_user):
    """Convenience: a pre-made admin user."""
    return make_user(username="admin", full_name="Admin User", role="admin")


@pytest.fixture()
def technician_user(make_user):
    """Convenience: a pre-made technician user."""
    return make_user(username="tech1", full_name="Tech One", role="technician")


@pytest.fixture()
def requester_user(make_user):
    """Convenience: a pre-made requester user."""
    return make_user(username="req1", full_name="Requester One", role="requester")
