"""
tests/test_db_connection.py
----------------------------
Tests for:
  - SQLite in-memory engine connectivity (tests run without PostgreSQL)
  - Schema creation (all tables present after bootstrap)
  - Session factory behaviour (commit, rollback, close)
  - create_tables_only() helper is idempotent
  - All expected table names exist in metadata
"""

import pytest
from sqlalchemy import inspect, text


# ---------------------------------------------------------------------------
# Engine / schema
# ---------------------------------------------------------------------------

class TestSchemaBootstrap:
    def test_engine_connects(self, db_session):
        """The test session can execute a trivial query."""
        result = db_session.execute(text("SELECT 1")).scalar()
        assert result == 1

    def test_all_tables_exist(self, db_session):
        """Every ORM-mapped table must be present after bootstrap."""
        from tests.conftest import _engine

        inspector = inspect(_engine)
        actual_tables = set(inspector.get_table_names())

        expected = {
            # original tables
            "users",
            "service_requests",
            "assignments",
            "status_history",
            # v2 tables
            "locations",
            "technician_skills",
            "request_comments",
            "request_history",
            "audit_log",
        }
        missing = expected - actual_tables
        assert not missing, f"Missing tables: {missing}"

    def test_create_tables_only_is_idempotent(self):
        """
        Calling create_all() twice on the test engine must not raise.
        checkfirst=True guarantees idempotency.

        We do NOT import database.connection here because that module
        instantiates a PostgreSQL engine at import time and psycopg2 is
        not available in a no-DB test environment.  Instead we call
        Base.metadata.create_all() directly — the same underlying operation.
        """
        from tests.conftest import _engine
        from database.models import Base

        # Schema was already created in conftest._bootstrap_schema().
        # A second call must complete silently.
        Base.metadata.create_all(bind=_engine, checkfirst=True)   # must not raise

    def test_users_columns(self, db_session):
        """Verify all expected columns exist on the users table."""
        from tests.conftest import _engine
        inspector = inspect(_engine)
        cols = {c["name"] for c in inspector.get_columns("users")}
        for expected_col in (
            "id", "username", "email", "password_hash", "full_name",
            "role", "is_active", "created_at", "updated_at", "last_login_at",
            "department", "phone",
        ):
            assert expected_col in cols, f"Column 'users.{expected_col}' missing"

    def test_service_requests_v2_columns(self, db_session):
        """Verify the v2 extended columns are present on service_requests."""
        from tests.conftest import _engine
        inspector = inspect(_engine)
        cols = {c["name"] for c in inspector.get_columns("service_requests")}
        for expected_col in (
            "location_id", "assigned_technician_id", "due_date",
            "ai_summary", "ai_recommendation",
        ):
            assert expected_col in cols, (
                f"v2 column 'service_requests.{expected_col}' missing"
            )

    def test_audit_log_columns(self, db_session):
        from tests.conftest import _engine
        inspector = inspect(_engine)
        cols = {c["name"] for c in inspector.get_columns("audit_log")}
        for expected_col in (
            "id", "user_id", "action", "entity_type", "entity_id",
            "detail", "outcome", "created_at",
        ):
            assert expected_col in cols


# ---------------------------------------------------------------------------
# Session behaviour
# ---------------------------------------------------------------------------

class TestSessionBehaviour:
    def test_flush_without_commit_is_visible_in_same_session(self, db_session, make_user):
        """flush() makes the row visible within the session."""
        user = make_user(username="flush_test")
        assert user.id is not None

        from database.models.user import User
        from sqlalchemy import select
        found = db_session.scalar(select(User).where(User.username == "flush_test"))
        assert found is not None
        assert found.id == user.id

    def test_session_isolation_between_tests_a(self, db_session, make_user):
        """Data written in this test must NOT appear in test_b (isolation check A)."""
        make_user(username="isolation_user_a")
        # Verify it exists in this session
        from database.models.user import User
        from sqlalchemy import select
        count = db_session.scalar(
            select(User).where(User.username == "isolation_user_a")
        )
        assert count is not None

    def test_session_isolation_between_tests_b(self, db_session):
        """isolation_user_a must not be present because test_a was rolled back."""
        from database.models.user import User
        from sqlalchemy import select
        found = db_session.scalar(
            select(User).where(User.username == "isolation_user_a")
        )
        assert found is None, (
            "isolation_user_a leaked between tests — session rollback is broken"
        )

    def test_foreign_key_enforcement(self, db_session):
        """
        Inserting a ServiceRequest with a non-existent requester_id
        must raise an IntegrityError on SQLite (PRAGMA foreign_keys=ON).
        """
        from database.models.request import ServiceRequest, RequestCategory, RequestPriority, RequestStatus
        from sqlalchemy.exc import IntegrityError

        req = ServiceRequest(
            reference_number="REQ-FK-TEST",
            requester_id=99999,       # does not exist
            title="FK violation test",
            description="Should fail",
            location="Nowhere",
            category=RequestCategory.OTHER,
            priority=RequestPriority.LOW,
            status=RequestStatus.OPEN,
        )
        db_session.add(req)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()
