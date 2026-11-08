"""
tests/test_qa_dashboard.py
---------------------------
QA tests for dashboard data aggregation: KPIs from real DB records,
empty states, location breakdown, overdue counts.

Uses CRUD layer functions directly (which accept a session parameter)
rather than the analytics_service wrappers (which call get_db() internally).
"""

import pytest
from datetime import datetime, timezone, timedelta

from database.models.request import (
    RequestCategory, RequestPriority, RequestStatus,
)
from database.crud.request_crud import (
    create_request, update_request_status, count_requests_by_status,
    count_requests_by_category, count_requests_by_priority,
    get_all_requests,
)
from database.crud.history_crud import record_request_created
from database.crud.assignment_crud import assign_request, get_technician_open_workload
from database.crud.user_crud import get_technicians


class TestDashboardKPIs:
    """KPIs must be calculated from actual database records."""

    def test_total_requests_count(self, db_session, make_user, make_request):
        user = make_user(username="kpi_user")
        make_request(requester=user, reference_suffix="KPI1")
        make_request(requester=user, reference_suffix="KPI2")
        db_session.flush()
        status_counts = count_requests_by_status(db_session)
        total = sum(status_counts.values())
        assert total >= 2

    def test_priority_breakdown_matches_db(self, db_session, make_user, make_request):
        user = make_user(username="pri_breakdown")
        make_request(requester=user, priority="critical", reference_suffix="PB1")
        make_request(requester=user, priority="high", reference_suffix="PB2")
        db_session.flush()
        breakdown = count_requests_by_priority(db_session)
        assert breakdown.get("critical", 0) >= 1
        assert breakdown.get("high", 0) >= 1

    def test_status_distribution_matches_db(self, db_session, make_user, make_request):
        user = make_user(username="status_dist")
        make_request(requester=user, status="submitted", reference_suffix="SD1")
        make_request(requester=user, status="resolved", reference_suffix="SD2")
        db_session.flush()
        dist = count_requests_by_status(db_session)
        assert dist.get("submitted", 0) >= 1
        assert dist.get("resolved", 0) >= 1

    def test_category_breakdown_matches_db(self, db_session, make_user, make_request):
        user = make_user(username="cat_breakdown")
        make_request(requester=user, category="plumbing", reference_suffix="CB1")
        make_request(requester=user, category="electrical", reference_suffix="CB2")
        db_session.flush()
        breakdown = count_requests_by_category(db_session)
        assert breakdown.get("plumbing", 0) >= 1
        assert breakdown.get("electrical", 0) >= 1

    def test_technician_workload_reflects_assignments(self, db_session, make_user, make_request):
        admin = make_user(username="wl_admin", role="admin")
        tech = make_user(username="wl_tech", role="technician")
        requester = make_user(username="wl_req", role="requester")
        req = make_request(requester=requester, reference_suffix="WL1", category="plumbing")
        record_request_created(db_session, req.id, requester.id, "requester")
        db_session.flush()
        assign_request(db_session, req.id, tech.id, admin.id)
        db_session.flush()
        workload = get_technician_open_workload(db_session)
        assert workload.get(tech.id, 0) >= 1


class TestOverdueDetection:
    def test_no_active_requests_on_empty(self, db_session):
        active = [r for r in get_all_requests(db_session)
                  if r.status.value in ("submitted", "assigned", "in_progress", "on_hold")]
        assert len(active) == 0

    def test_sla_breach_detected(self, db_session, make_user, make_request):
        user = make_user(username="sla_user")
        req = make_request(requester=user, priority="critical", status="assigned",
                           reference_suffix="SLA1")
        req.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        db_session.flush()
        active = [r for r in get_all_requests(db_session)
                  if r.status.value in ("submitted", "assigned", "in_progress", "on_hold")]
        assert len(active) >= 1
        # The request is 2 days old with critical priority (SLA = 4 hours)
        from business.analytics_service import SLA_HOURS
        for r in active:
            age = (datetime.now(timezone.utc) - r.created_at).total_seconds() / 3600
            sla = SLA_HOURS.get(r.priority.value, 24)
            if r.id == req.id:
                assert age > sla, f"Request should breach SLA (age={age:.1f}h > sla={sla}h)"


class TestLocationBreakdown:
    def test_location_breakdown_empty(self, db_session):
        reqs = get_all_requests(db_session)
        locations = set(r.location for r in reqs if r.location)
        assert len(locations) == 0

    def test_location_breakdown_with_data(self, db_session, make_user, make_request, make_location):
        user = make_user(username="loc_user")
        loc = make_location(building_name="QA Building")
        req = make_request(requester=user, reference_suffix="LOC1")
        req.location = loc.display_name()
        req.building = loc.building_name
        db_session.flush()
        reqs = get_all_requests(db_session)
        locations = set(r.location for r in reqs if r.location)
        assert loc.display_name() in locations


class TestResolutionTimeStats:
    def test_no_resolved_on_empty(self, db_session):
        resolved = [r for r in get_all_requests(db_session)
                    if r.status.value in ("resolved", "closed")]
        assert len(resolved) == 0

    def test_stats_with_resolved_request(self, db_session, make_user, make_request):
        user = make_user(username="res_stats_user")
        req = make_request(requester=user, status="resolved", reference_suffix="RS1")
        req.created_at = datetime.now(timezone.utc) - timedelta(hours=10)
        req.resolved_at = datetime.now(timezone.utc)
        db_session.flush()
        resolved = [r for r in get_all_requests(db_session)
                    if r.status.value in ("resolved", "closed")]
        assert len(resolved) >= 1
        for r in resolved:
            if r.resolved_at and r.created_at:
                hours = (r.resolved_at - r.created_at).total_seconds() / 3600
                assert hours >= 0
