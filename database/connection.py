"""
database/connection.py
----------------------
SQLAlchemy engine, session factory, and database initialisation.

Usage:
    from database.connection import get_db, init_db

    # As a context manager (preferred for CRUD ops):
    with get_db() as session:
        session.add(obj)
        session.commit()

    # One-time setup (called from app.py on startup):
    init_db()

v2 changes:
  - Default admin seed REMOVED.  Use `scripts/create_admin.py` to create
    the first administrator interactively.  Shipping a known default password
    is a security anti-pattern.
  - New helper create_tables_only() used by the test suite with an
    injected engine so tests never touch the real database.
  - All new v2 models imported inside init_db() so they are discovered.
"""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _build_database_url() -> str:
    """Construct the PostgreSQL connection URL from settings."""
    if settings.DATABASE_URL:
        return settings.DATABASE_URL
    return (
        f"postgresql://{settings.DB_USER}:{settings.DB_PASSWORD}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
    )


def _create_engine():
    """Create and configure the SQLAlchemy engine."""
    url = _build_database_url()

    # Use PostgreSQL-specific settings only for PostgreSQL URLs.
    # SQLite (used in tests) doesn't support QueuePool or these params.
    is_sqlite = url.startswith("sqlite")

    if is_sqlite:
        engine = create_engine(
            url,
            echo=settings.APP_ENV == "development",
            connect_args={},
        )
    else:
        engine = create_engine(
            url,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=settings.APP_ENV == "development",
            connect_args={
                "connect_timeout": 10,
                "application_name": "FacilityOps Pulse",
            },
        )

    @event.listens_for(engine, "connect")
    def on_connect(dbapi_connection, connection_record):
        logger.debug("New database connection established.")

    return engine


try:
    engine = _create_engine()
    logger.info("Database engine created successfully.")
except Exception as exc:
    logger.critical("Failed to create database engine: %s", exc)
    raise


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """
    Context manager that provides a transactional database session.

    Commits on clean exit, rolls back on any exception, and always closes.
    """
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.error("Database error — transaction rolled back: %s", exc)
        raise
    except Exception as exc:
        session.rollback()
        logger.error("Unexpected error — transaction rolled back: %s", exc)
        raise
    finally:
        session.close()


def make_session_factory(bind_engine: Engine) -> sessionmaker:
    """
    Return a new sessionmaker bound to *bind_engine*.
    Used by the test suite to inject an in-memory SQLite engine.
    """
    return sessionmaker(
        bind=bind_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


# ---------------------------------------------------------------------------
# Schema creation helpers
# ---------------------------------------------------------------------------

def _import_all_models() -> None:
    """
    Import every ORM model so SQLAlchemy registers all tables with
    Base.metadata before create_all() is called.
    """
    from database.models import Base              # noqa: F401 — side-effect
    # original
    from database.models.user import User          # noqa: F401
    from database.models.request import ServiceRequest  # noqa: F401
    from database.models.assignment import Assignment    # noqa: F401
    from database.models.status_history import StatusHistory  # noqa: F401
    # v2
    from database.models.location import Location         # noqa: F401
    from database.models.technician_skill import TechnicianSkill  # noqa: F401
    from database.models.request_comment import RequestComment    # noqa: F401
    from database.models.request_history import RequestHistory    # noqa: F401
    from database.models.audit_log import AuditLog                # noqa: F401


def create_tables_only(bind_engine: Engine | None = None) -> None:
    """
    Create all tables on *bind_engine* (defaults to the module-level engine).
    Does NOT seed any data.  Safe to call from tests with a disposable engine.
    """
    from database.models import Base
    _import_all_models()
    target = bind_engine if bind_engine is not None else engine
    Base.metadata.create_all(bind=target, checkfirst=True)


def init_db() -> None:
    """
    Create all tables defined in the ORM models.

    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS semantics.

    NOTE (v2): The automatic default-admin seed has been REMOVED.
    Run `python scripts/create_admin.py` once after a fresh database setup
    to create the first administrator account interactively.
    """
    try:
        logger.info("Initialising database schema…")
        create_tables_only()
        logger.info("Schema ready. All tables created (or already exist).")
        _warn_if_no_admin()
    except OperationalError as exc:
        logger.critical(
            "Cannot connect to PostgreSQL. Check DB_HOST / DB_PORT / DB_NAME "
            "in your .env file. Error: %s",
            exc,
        )
        raise


def _warn_if_no_admin() -> None:
    """
    Log a one-time startup warning if no admin user exists yet.
    Guides operators to run the setup script — does not create any account.
    """
    from database.models.user import User, UserRole
    try:
        with get_db() as session:
            exists = session.query(User).filter_by(role=UserRole.ADMIN).first()
        if not exists:
            logger.warning(
                "⚠️  No administrator account found in the database. "
                "Run `python scripts/create_admin.py` to create the first admin."
            )
    except Exception as exc:
        logger.warning("Could not check for admin account: %s", exc)


def check_db_connection() -> tuple[bool, str]:
    """
    Probe the database connection. Returns (success: bool, message: str).
    Used by the UI to show a friendly error instead of a traceback.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "Connected"
    except OperationalError as exc:
        return False, f"Cannot reach PostgreSQL: {exc.orig}"
    except Exception as exc:
        return False, f"Unexpected error: {exc}"
