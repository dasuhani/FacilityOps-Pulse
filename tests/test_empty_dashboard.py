"""
tests/test_empty_dashboard.py
------------------------------
Regression tests for empty-database dashboard analytics.

Verifies that every analytics function returns sensible empty-state
results (zero counts, None averages, empty dicts/lists) instead of
raising KeyError or other exceptions when the database has no requests.

Also tests a populated scenario to confirm the fix doesn't break
normal operation.

All tests mock get_requests_dataframe() to return a properly-schema'd
empty DataFrame, simulating the real empty-database scenario without
needing a real database connection.
"""

import pytest
import pandas as pd
from unittest.mock import patch
from datetime import datetime, timezone, timedelta


# Schema that get_requests_dataframe() guarantees even when empty
_EMPTY_DF = pd.DataFrame(columns=[
    "id", "reference_number", "title", "category", "priority",
    "status", "location", "created_at", "resolved_at", "requester_id",
    "technician_name",
])


# ---------------------------------------------------------------------------
# Tests for the empty-database scenario
# ---------------------------------------------------------------------------

class TestEmptyDataFrame:
    """Verify get_requests_dataframe returns a proper schema when empty."""

    def test_empty_dataframe_has_columns(self):
        from business.analytics_service import get_requests_dataframe
        with patch("business.analytics_service.get_requests_dataframe_raw", return_value=[]):
            df = get_requests_dataframe()
        assert isinstance(df, pd.DataFrame)
        for col in ("status", "priority", "created_at", "resolved_at",
                     "category", "location", "technician_name"):
            assert col in df.columns, f"Column '{col}' missing from empty DataFrame"

    def test_empty_dataframe_is_empty(self):
        from business.analytics_service import get_requests_dataframe
        with patch("business.analytics_service.get_requests_dataframe_raw", return_value=[]):
            df = get_requests_dataframe()
        assert df.empty
        assert len(df) == 0


class TestEmptyResolutionStats:
    """get_resolution_time_stats must not crash on empty DB."""

    def test_empty_stats_no_crash(self):
        from business.analytics_service import get_resolution_time_stats
        with patch("business.analytics_service.get_requests_dataframe", return_value=_EMPTY_DF):
            stats = get_resolution_time_stats(days=None)
        assert stats["count"] == 0
        assert stats["avg_hours"] is None
        assert stats["median_hours"] is None
        assert stats["min_hours"] is None
        assert stats["max_hours"] is None

    def test_empty_stats_with_days(self):
        from business.analytics_service import get_resolution_time_stats
        with patch("business.analytics_service.get_requests_dataframe", return_value=_EMPTY_DF):
            stats = get_resolution_time_stats(days=30)
        assert stats["count"] == 0
        assert stats["avg_hours"] is None


class TestEmptySLADetection:
    """SLA functions must return 0 / empty on empty DB."""

    def test_sla_breach_count_zero(self):
        from business.analytics_service import get_sla_breach_count
        with patch("business.analytics_service.get_requests_dataframe", return_value=_EMPTY_DF):
            assert get_sla_breach_count() == 0

    def test_sla_breach_requests_empty(self):
        from business.analytics_service import get_sla_breach_requests
        with patch("business.analytics_service.get_requests_dataframe", return_value=_EMPTY_DF):
            result = get_sla_breach_requests()
        assert result.empty

    def test_overdue_count_zero(self):
        from business.analytics_service import get_overdue_count
        with patch("business.analytics_service.get_requests_dataframe", return_value=_EMPTY_DF):
            assert get_overdue_count() == 0


class TestEmptyLocationBreakdown:
    def test_location_breakdown_empty(self):
        from business.analytics_service import get_location_breakdown
        with patch("business.analytics_service.get_requests_dataframe", return_value=_EMPTY_DF):
            result = get_location_breakdown()
        assert result == {} or all(v == 0 for v in result.values())


class TestEmptyRequestsOverTime:
    def test_requests_over_time_empty(self):
        from business.analytics_service import get_requests_over_time
        with patch("business.analytics_service.get_requests_dataframe", return_value=_EMPTY_DF):
            df = get_requests_over_time(days=30)
        assert isinstance(df, pd.DataFrame)
        assert "date" in df.columns
        assert "count" in df.columns


class TestEmptySummaryCounts:
    """These use direct DB queries via the CRUD layer (session-passing)."""

    def test_summary_counts_all_zero(self, db_session):
        from database.crud.request_crud import (
            count_requests_by_status, count_requests_by_category, count_requests_by_priority,
        )
        status = count_requests_by_status(db_session)
        category = count_requests_by_category(db_session)
        priority = count_requests_by_priority(db_session)
        assert sum(status.values()) == 0
        assert sum(priority.values()) == 0
        assert priority.get("critical", 0) == 0
        assert priority.get("high", 0) == 0
        assert status.get("resolved", 0) == 0


# ---------------------------------------------------------------------------
# Tests for the populated scenario (regression — verify fix doesn't break)
# ---------------------------------------------------------------------------

class TestPopulatedResolutionStats:
    """Verify get_resolution_time_stats processes resolved requests correctly."""

    def test_stats_with_resolved_data(self):
        from business.analytics_service import get_resolution_time_stats
        now = datetime.now(timezone.utc)
        df = pd.DataFrame([
            {"id": 1, "reference_number": "REQ-001", "title": "Test",
             "category": "plumbing", "priority": "high", "status": "resolved",
             "location": "Building A", "created_at": now - timedelta(hours=10),
             "resolved_at": now, "requester_id": 1, "technician_name": None},
        ])
        with patch("business.analytics_service.get_requests_dataframe", return_value=df):
            stats = get_resolution_time_stats(days=None)
        assert stats["count"] == 1
        assert stats["avg_hours"] is not None
        assert 9 <= stats["avg_hours"] <= 11

    def test_stats_filters_by_period(self):
        from business.analytics_service import get_resolution_time_stats
        now = datetime.now(timezone.utc)
        df = pd.DataFrame([
            {"id": 1, "reference_number": "REQ-001", "title": "Old",
             "category": "other", "priority": "low", "status": "resolved",
             "location": "A", "created_at": now - timedelta(days=40),
             "resolved_at": now - timedelta(days=39), "requester_id": 1, "technician_name": None},
            {"id": 2, "reference_number": "REQ-002", "title": "Recent",
             "category": "other", "priority": "low", "status": "resolved",
             "location": "B", "created_at": now - timedelta(days=5),
             "resolved_at": now, "requester_id": 1, "technician_name": None},
        ])
        with patch("business.analytics_service.get_requests_dataframe", return_value=df):
            stats_30 = get_resolution_time_stats(days=30)
        assert stats_30["count"] == 1

        with patch("business.analytics_service.get_requests_dataframe", return_value=df):
            stats_all = get_resolution_time_stats(days=None)
        assert stats_all["count"] == 2


class TestPopulatedSLA:
    def test_sla_breach_detected(self):
        from business.analytics_service import get_sla_breach_count
        now = datetime.now(timezone.utc)
        df = pd.DataFrame([
            {"id": 1, "reference_number": "REQ-001", "title": "Old critical",
             "category": "other", "priority": "critical", "status": "assigned",
             "location": "A", "created_at": now - timedelta(days=2),
             "resolved_at": None, "requester_id": 1, "technician_name": None},
        ])
        with patch("business.analytics_service.get_requests_dataframe", return_value=df):
            assert get_sla_breach_count() >= 1

    def test_no_breach_for_recent(self):
        from business.analytics_service import get_sla_breach_count
        now = datetime.now(timezone.utc)
        df = pd.DataFrame([
            {"id": 1, "reference_number": "REQ-001", "title": "Recent low",
             "category": "other", "priority": "low", "status": "submitted",
             "location": "A", "created_at": now - timedelta(hours=1),
             "resolved_at": None, "requester_id": 1, "technician_name": None},
        ])
        with patch("business.analytics_service.get_requests_dataframe", return_value=df):
            assert get_sla_breach_count() == 0


class TestPopulatedLocationBreakdown:
    def test_location_breakdown_with_data(self):
        from business.analytics_service import get_location_breakdown
        df = pd.DataFrame([
            {"id": 1, "location": "Building A", "building": "Building A",
             "status": "submitted", "priority": "low", "category": "other",
             "created_at": datetime.now(timezone.utc), "resolved_at": None,
             "technician_name": None, "requester_id": 1, "reference_number": "R1",
             "title": "T"},
        ])
        with patch("business.analytics_service.get_requests_dataframe", return_value=df):
            breakdown = get_location_breakdown()
        assert len(breakdown) >= 1
        assert "Building A" in breakdown


class TestPopulatedRequestsOverTime:
    def test_requests_over_time_with_data(self):
        from business.analytics_service import get_requests_over_time
        now = datetime.now(timezone.utc)
        df = pd.DataFrame([
            {"id": 1, "reference_number": "R1", "title": "T",
             "category": "other", "priority": "low", "status": "submitted",
             "location": "A", "created_at": now - timedelta(days=1),
             "resolved_at": None, "requester_id": 1, "technician_name": None},
        ])
        with patch("business.analytics_service.get_requests_dataframe", return_value=df):
            daily_df = get_requests_over_time(days=30)
        assert not daily_df.empty
        assert "date" in daily_df.columns
        assert "count" in daily_df.columns
