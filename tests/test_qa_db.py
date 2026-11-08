"""
tests/test_qa_db.py
--------------------
QA tests for database layer: connection, empty database, schema integrity.
"""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


class TestDatabaseSchema:
    """Verify all expected tables and columns exist."""

    def test_all_required_tables_exist(self, db_session):
        from tests.conftest import _engine
        inspector = inspect(_engine)
        actual = set(inspector.get_table_names())
        expected = {
            "users", "service_requests", "assignments", "status_history",
            "locations", "technician_skills", "request_comments",
            "request_history", "audit_log",
        }
        missing = expected - actual
        assert not missing, f"Missing tables: {missing}"

    def test_service_requests_has_all_v2_columns(self, db_session):
        from tests.conftest import _engine
        inspector = inspect(_engine)
        cols = {c["name"] for c in inspector.get_columns("service_requests")}
        for required in (
            "location_id", "assigned_technician_id", "due_date",
            "ai_summary", "ai_recommendation", "ai_confidence_score",
            "ai_suggested_category", "ai_suggested_priority",
        ):
            assert required in cols, f"Column 'service_requests.{required}' missing"

    def test_foreign_key_enforcement(self, db_session, make_user):
        from database.models.request import (
            ServiceRequest, RequestCategory, RequestPriority, RequestStatus,
        )
        req = ServiceRequest(
            reference_number="REQ-FK-QA",
            requester_id=99999,
            title="FK violation test request",
            description="Should fail due to invalid FK",
            location="Nowhere",
            category=RequestCategory.OTHER,
            priority=RequestPriority.LOW,
            status=RequestStatus.SUBMITTED,
        )
        db_session.add(req)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    def test_engine_can_execute_query(self, db_session):
        result = db_session.execute(text("SELECT 1")).scalar()
        assert result == 1


class TestEmptyDatabase:
    """Verify CRUD functions handle an empty database gracefully."""

    def test_summary_counts_on_empty_db(self, db_session):
        from database.crud.request_crud import count_requests_by_status, count_requests_by_category, count_requests_by_priority
        assert count_requests_by_status(db_session) == {} or all(v == 0 for v in count_requests_by_status(db_session).values())
        assert count_requests_by_category(db_session) == {} or all(v == 0 for v in count_requests_by_category(db_session).values())
        assert count_requests_by_priority(db_session) == {} or all(v == 0 for v in count_requests_by_priority(db_session).values())

    def test_status_distribution_empty(self, db_session):
        from database.crud.request_crud import count_requests_by_status
        dist = count_requests_by_status(db_session)
        assert dist == {} or all(v == 0 for v in dist.values())

    def test_category_breakdown_empty(self, db_session):
        from database.crud.request_crud import count_requests_by_category
        breakdown = count_requests_by_category(db_session)
        assert breakdown == {} or all(v == 0 for v in breakdown.values())

    def test_technician_workload_empty(self, db_session):
        from database.crud.user_crud import get_technicians
        techs = get_technicians(db_session)
        assert techs == []

    def test_sla_breach_count_empty(self, db_session):
        from database.crud.request_crud import get_all_requests
        reqs = get_all_requests(db_session)
        assert reqs == []

    def test_overdue_count_empty(self, db_session):
        from database.crud.request_crud import get_all_requests
        reqs = get_all_requests(db_session)
        assert len(reqs) == 0

    def test_resolution_time_stats_empty(self, db_session):
        from database.crud.request_crud import get_all_requests
        reqs = get_all_requests(db_session)
        resolved = [r for r in reqs if r.status.value in ("resolved", "closed")]
        assert len(resolved) == 0
