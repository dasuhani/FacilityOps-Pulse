"""
tests/test_requests.py
-----------------------
Tests for:
  - ServiceRequest CRUD (create, read, filter, update status/priority)
  - Reference number generation
  - v2 fields (location_id, due_date, ai_summary, ai_recommendation,
    assigned_technician_id)
  - Status transitions and history entries
  - Assignment CRUD (assign, reassign, unassign, workload)
  - RequestComment (add, read, empty/too-long rejection)
  - RequestHistory entries
  - AuditLog entries for request operations
  - Location CRUD
"""

import pytest
from datetime import datetime, timezone, timedelta

from database.models.request import (
    RequestCategory, RequestPriority, RequestStatus
)
from database.models.request_history import HistoryEventType
from database.crud.request_crud import (
    create_request,
    get_request_by_id,
    get_request_by_reference,
    get_requests_for_requester,
    get_requests_for_technician,
    get_all_requests,
    update_request_status,
    update_request_ai_fields,
    update_request_priority,
    update_resolution_notes,
    update_request_v2_fields,
    write_request_history,
    count_requests_by_status,
    count_requests_by_category,
)
from database.crud.assignment_crud import (
    assign_request,
    unassign_request,
    get_assignment_by_request,
    get_technician_open_workload,
)
from database.crud.history_crud import (
    get_history_for_request,
    record_request_created,
    create_history_entry,
)
from database.crud.comment_crud import (
    add_comment,
    get_comments_for_request,
    count_comments_for_request,
    COMMENT_MAX_LEN,
)
from database.crud.location_crud import (
    create_location,
    get_location_by_id,
    get_all_locations,
    update_location,
    set_location_active,
    search_locations,
)
from database.crud.audit_crud import (
    log_request_created,
    log_request_status_changed,
    get_audit_for_entity,
)


# ---------------------------------------------------------------------------
# Location CRUD
# ---------------------------------------------------------------------------

class TestLocationCRUD:
    def test_create_location(self, db_session):
        loc = create_location(db_session, building_name="HQ Tower", floor="3", area="Finance")
        assert loc.id is not None
        assert loc.building_name == "HQ Tower"
        assert loc.floor == "3"

    def test_display_name_all_parts(self, db_session):
        loc = create_location(db_session, building_name="Block B", floor="2", area="Server Room")
        assert loc.display_name() == "Block B › Floor 2 › Server Room"

    def test_display_name_building_only(self, db_session):
        loc = create_location(db_session, building_name="Annex")
        assert loc.display_name() == "Annex"

    def test_create_empty_building_raises(self, db_session):
        with pytest.raises(ValueError, match="must not be empty"):
            create_location(db_session, building_name="  ")

    def test_get_all_locations_active_only(self, db_session, make_location):
        make_location(building_name="Active Loc", is_active=1)
        make_location(building_name="Inactive Loc", is_active=0)
        locs = get_all_locations(db_session, active_only=True)
        names = [l.building_name for l in locs]
        assert "Active Loc" in names
        assert "Inactive Loc" not in names

    def test_search_locations(self, db_session, make_location):
        make_location(building_name="Science Wing")
        results = search_locations(db_session, "Science")
        assert any(l.building_name == "Science Wing" for l in results)

    def test_update_location(self, db_session, make_location):
        loc = make_location(building_name="Old Name")
        updated = update_location(db_session, loc.id, building_name="New Name")
        assert updated.building_name == "New Name"

    def test_set_location_inactive(self, db_session, make_location):
        loc = make_location(building_name="To Retire")
        set_location_active(db_session, loc.id, False)
        refreshed = get_location_by_id(db_session, loc.id)
        assert refreshed.is_active == 0


# ---------------------------------------------------------------------------
# ServiceRequest creation
# ---------------------------------------------------------------------------

class TestCreateRequest:
    def test_create_basic_request(self, db_session, make_user):
        requester = make_user(username="create_req_user")
        req = create_request(
            db_session,
            requester_id=requester.id,
            title="Fix broken pipe in bathroom",
            description="Water leaking from pipe under sink in 3rd floor restroom.",
            location="Building A, Floor 3",
        )
        assert req.id is not None
        assert req.reference_number.startswith("REQ-")
        assert req.status == RequestStatus.SUBMITTED
        assert req.requester_id == requester.id

    def test_reference_number_increments(self, db_session, make_user):
        req_user = make_user(username="ref_inc_user")
        r1 = create_request(
            db_session, requester_id=req_user.id,
            title="First request title text", description="First desc text here.", location="Room 1"
        )
        r2 = create_request(
            db_session, requester_id=req_user.id,
            title="Second request title text", description="Second desc text here.", location="Room 2"
        )
        # Reference numbers must be different
        assert r1.reference_number != r2.reference_number

    def test_default_status_is_open(self, db_session, make_user):
        user = make_user(username="default_status")
        req = create_request(
            db_session, requester_id=user.id,
            title="Default status check", description="Should default to SUBMITTED.", location="Room X"
        )
        assert req.status == RequestStatus.SUBMITTED

    def test_default_priority_is_medium(self, db_session, make_user):
        user = make_user(username="default_pri")
        req = create_request(
            db_session, requester_id=user.id,
            title="Priority check title text", description="Should default to MEDIUM.", location="Y"
        )
        assert req.priority == RequestPriority.MEDIUM

    def test_v2_fields_can_be_set(self, db_session, make_user, make_location):
        user = make_user(username="v2_fields_user")
        loc = make_location(building_name="V2 Building")
        due = datetime.now(timezone.utc) + timedelta(days=3)

        req = create_request(
            db_session, requester_id=user.id,
            title="V2 field test title text", description="Testing v2 extended fields.", location="Z"
        )
        update_request_v2_fields(
            db_session,
            request_id=req.id,
            location_id=loc.id,
            due_date=due,
            ai_summary="Short summary.",
            ai_recommendation="Do this first.",
        )
        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.location_id == loc.id
        assert refreshed.ai_summary == "Short summary."
        assert refreshed.ai_recommendation == "Do this first."
        assert refreshed.due_date is not None


# ---------------------------------------------------------------------------
# Read / filter operations
# ---------------------------------------------------------------------------

class TestReadRequests:
    def test_get_by_id(self, db_session, make_request):
        req = make_request(reference_suffix="R001")
        found = get_request_by_id(db_session, req.id)
        assert found is not None
        assert found.id == req.id

    def test_get_by_id_missing_returns_none(self, db_session):
        assert get_request_by_id(db_session, 99999) is None

    def test_get_by_reference(self, db_session, make_request):
        req = make_request(reference_suffix="R002")
        found = get_request_by_reference(db_session, req.reference_number)
        assert found is not None

    def test_get_requests_for_requester_own_only(self, db_session, make_user, make_request):
        owner = make_user(username="owner_req")
        other = make_user(username="other_req")
        r1 = make_request(requester=owner, reference_suffix="O001")
        r2 = make_request(requester=other, reference_suffix="O002")

        results = get_requests_for_requester(db_session, requester_id=owner.id)
        ids = [r.id for r in results]
        assert r1.id in ids
        assert r2.id not in ids

    def test_get_requests_filter_by_status(self, db_session, make_user, make_request):
        user = make_user(username="status_filter_user")
        open_req = make_request(requester=user, status="submitted", reference_suffix="SF1")
        closed_req = make_request(requester=user, status="closed", reference_suffix="SF2")

        results = get_requests_for_requester(
            db_session, requester_id=user.id,
            status_filter=[RequestStatus.SUBMITTED]
        )
        ids = [r.id for r in results]
        assert open_req.id in ids
        assert closed_req.id not in ids

    def test_get_all_requests_search(self, db_session, make_user, make_request):
        user = make_user(username="search_user")
        make_request(
            requester=user, title="HVAC unit failure in room 302",
            reference_suffix="SRC1"
        )
        make_request(
            requester=user, title="Printer jam on floor two",
            reference_suffix="SRC2"
        )
        results = get_all_requests(db_session, search_query="HVAC")
        titles = [r.title for r in results]
        assert "HVAC unit failure in room 302" in titles
        assert "Printer jam on floor two" not in titles

    def test_count_by_status(self, db_session, make_user, make_request):
        user = make_user(username="count_status_user")
        make_request(requester=user, status="submitted", reference_suffix="CS1")
        make_request(requester=user, status="submitted", reference_suffix="CS2")
        make_request(requester=user, status="resolved", reference_suffix="CS3")
        counts = count_requests_by_status(db_session)
        assert counts.get("submitted", 0) >= 2
        assert counts.get("resolved", 0) >= 1


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------

class TestStatusTransitions:
    def test_update_status_changes_field(self, db_session, make_user, make_request):
        user = make_user(username="status_changer")
        req = make_request(requester=user, reference_suffix="ST1")
        record_request_created(db_session, req.id, user.id, "requester")

        update_request_status(
            db_session, req.id,
            new_status=RequestStatus.IN_PROGRESS,
            changed_by_id=user.id,
            changed_by_role="admin",
        )
        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.status == RequestStatus.IN_PROGRESS

    def test_resolved_sets_resolved_at(self, db_session, make_user, make_request):
        user = make_user(username="resolve_user")
        req = make_request(requester=user, reference_suffix="RS1")
        record_request_created(db_session, req.id, user.id, "requester")

        update_request_status(
            db_session, req.id,
            new_status=RequestStatus.RESOLVED,
            changed_by_id=user.id,
            changed_by_role="technician",
        )
        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.resolved_at is not None

    def test_status_update_writes_status_history(self, db_session, make_user, make_request):
        user = make_user(username="hist_user")
        req = make_request(requester=user, reference_suffix="SH1")
        record_request_created(db_session, req.id, user.id, "requester")

        update_request_status(
            db_session, req.id,
            new_status=RequestStatus.ON_HOLD,
            changed_by_id=user.id,
            changed_by_role="admin",
            note="Waiting for parts.",
        )
        history = get_history_for_request(db_session, req.id)
        # Should have: created entry + ON_HOLD entry
        statuses = [h.new_status for h in history]
        assert RequestStatus.ON_HOLD in statuses

    def test_update_nonexistent_request_raises(self, db_session, make_user):
        user = make_user(username="no_req_user")
        with pytest.raises(ValueError, match="not found"):
            update_request_status(
                db_session, 99999,
                new_status=RequestStatus.CLOSED,
                changed_by_id=user.id,
                changed_by_role="admin",
            )

    def test_priority_update(self, db_session, make_user, make_request):
        user = make_user(username="pri_updater")
        req = make_request(requester=user, priority="low", reference_suffix="PU1")
        update_request_priority(db_session, req.id, RequestPriority.CRITICAL, user.id)
        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.priority == RequestPriority.CRITICAL

    def test_resolution_notes_saved(self, db_session, make_user, make_request):
        user = make_user(username="res_notes_user")
        req = make_request(requester=user, reference_suffix="RN1")
        update_resolution_notes(db_session, req.id, "Replaced the broken part.")
        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.resolution_notes == "Replaced the broken part."


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

class TestAssignment:
    def test_assign_request_to_technician(self, db_session, make_user, make_request):
        admin = make_user(username="assign_admin", role="admin")
        tech = make_user(username="assign_tech", role="technician")
        req = make_request(reference_suffix="AS1")
        record_request_created(db_session, req.id, req.requester_id, "requester")

        assignment = assign_request(
            db_session,
            request_id=req.id,
            technician_id=tech.id,
            assigned_by_id=admin.id,
        )
        assert assignment.id is not None
        assert assignment.technician_id == tech.id

    def test_assign_transitions_submitted_to_assigned(self, db_session, make_user, make_request):
        admin = make_user(username="trans_admin", role="admin")
        tech = make_user(username="trans_tech", role="technician")
        req = make_request(status="submitted", reference_suffix="TR1")
        record_request_created(db_session, req.id, req.requester_id, "requester")

        assign_request(db_session, req.id, tech.id, admin.id)
        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.status == RequestStatus.ASSIGNED

    def test_assign_syncs_denorm_field(self, db_session, make_user, make_request):
        admin = make_user(username="denorm_admin", role="admin")
        tech = make_user(username="denorm_tech", role="technician")
        req = make_request(reference_suffix="DN1")
        record_request_created(db_session, req.id, req.requester_id, "requester")

        assign_request(db_session, req.id, tech.id, admin.id)
        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.assigned_technician_id == tech.id

    def test_reassign_updates_technician(self, db_session, make_user, make_request):
        admin = make_user(username="re_admin", role="admin")
        tech1 = make_user(username="re_tech1", role="technician")
        tech2 = make_user(username="re_tech2", role="technician")
        req = make_request(reference_suffix="RA1")
        record_request_created(db_session, req.id, req.requester_id, "requester")

        assign_request(db_session, req.id, tech1.id, admin.id)
        assign_request(db_session, req.id, tech2.id, admin.id)  # re-assign

        assignment = get_assignment_by_request(db_session, req.id)
        assert assignment.technician_id == tech2.id

    def test_unassign_clears_assignment(self, db_session, make_user, make_request):
        admin = make_user(username="un_admin", role="admin")
        tech = make_user(username="un_tech", role="technician")
        req = make_request(reference_suffix="UA1")
        record_request_created(db_session, req.id, req.requester_id, "requester")

        assign_request(db_session, req.id, tech.id, admin.id)
        unassign_request(db_session, req.id, admin.id)

        assert get_assignment_by_request(db_session, req.id) is None
        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.assigned_technician_id is None

    def test_unassign_returns_request_to_submitted(self, db_session, make_user, make_request):
        admin = make_user(username="unop_admin", role="admin")
        tech = make_user(username="unop_tech", role="technician")
        req = make_request(status="submitted", reference_suffix="UO1")
        record_request_created(db_session, req.id, req.requester_id, "requester")

        assign_request(db_session, req.id, tech.id, admin.id)
        unassign_request(db_session, req.id, admin.id)
        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.status == RequestStatus.SUBMITTED

    def test_technician_queue_shows_assigned_requests(self, db_session, make_user, make_request):
        admin = make_user(username="q_admin", role="admin")
        tech = make_user(username="q_tech", role="technician")
        req = make_request(reference_suffix="Q1")
        record_request_created(db_session, req.id, req.requester_id, "requester")
        assign_request(db_session, req.id, tech.id, admin.id)

        results = get_requests_for_technician(db_session, technician_id=tech.id)
        ids = [r.id for r in results]
        assert req.id in ids

    def test_workload_counts_open_requests(self, db_session, make_user, make_request):
        admin = make_user(username="wl_admin", role="admin")
        tech = make_user(username="wl_tech", role="technician")

        for i in range(3):
            r = make_request(reference_suffix=f"WL{i}")
            record_request_created(db_session, r.id, r.requester_id, "requester")
            assign_request(db_session, r.id, tech.id, admin.id)

        workload = get_technician_open_workload(db_session)
        assert workload.get(tech.id, 0) == 3


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

class TestRequestComments:
    def test_add_comment(self, db_session, make_user, make_request):
        user = make_user(username="commenter")
        req = make_request(requester=user, reference_suffix="CM1")
        comment = add_comment(db_session, req.id, user.id, "This is my comment.")
        assert comment.id is not None
        assert comment.comment == "This is my comment."

    def test_empty_comment_raises(self, db_session, make_user, make_request):
        user = make_user(username="empty_commenter")
        req = make_request(requester=user, reference_suffix="CM2")
        with pytest.raises(ValueError, match="must not be empty"):
            add_comment(db_session, req.id, user.id, "   ")

    def test_too_long_comment_raises(self, db_session, make_user, make_request):
        user = make_user(username="long_commenter")
        req = make_request(requester=user, reference_suffix="CM3")
        with pytest.raises(ValueError, match="maximum length"):
            add_comment(db_session, req.id, user.id, "x" * (COMMENT_MAX_LEN + 1))

    def test_get_comments_returns_all(self, db_session, make_user, make_request):
        user = make_user(username="get_commenter")
        req = make_request(requester=user, reference_suffix="CM4")
        add_comment(db_session, req.id, user.id, "First comment.")
        add_comment(db_session, req.id, user.id, "Second comment.")
        comments = get_comments_for_request(db_session, req.id, load_user=False)
        assert len(comments) == 2

    def test_count_comments(self, db_session, make_user, make_request):
        user = make_user(username="count_commenter")
        req = make_request(requester=user, reference_suffix="CM5")
        add_comment(db_session, req.id, user.id, "One.")
        add_comment(db_session, req.id, user.id, "Two.")
        assert count_comments_for_request(db_session, req.id) == 2


# ---------------------------------------------------------------------------
# RequestHistory and AuditLog
# ---------------------------------------------------------------------------

class TestRequestHistoryAndAudit:
    def test_write_request_history(self, db_session, make_user, make_request):
        user = make_user(username="hist_writer")
        req = make_request(requester=user, reference_suffix="RH1")
        entry = write_request_history(
            db_session,
            request_id=req.id,
            changed_by=user.id,
            event_type=HistoryEventType.CREATED,
            new_status="submitted",
            note="Request submitted.",
        )
        assert entry.id is not None
        assert entry.event_type == HistoryEventType.CREATED

    def test_audit_log_request_created(self, db_session, make_user, make_request):
        user = make_user(username="audit_req")
        req = make_request(requester=user, reference_suffix="AR1")
        log_request_created(db_session, user_id=user.id, request_id=req.id)

        entries = get_audit_for_entity(db_session, "request", req.id)
        assert any(e.action == "request.created" for e in entries)

    def test_audit_log_status_changed(self, db_session, make_user, make_request):
        user = make_user(username="audit_status")
        req = make_request(requester=user, reference_suffix="AS2")
        record_request_created(db_session, req.id, user.id, "requester")
        log_request_status_changed(
            db_session, user_id=user.id, request_id=req.id,
            old_status="submitted", new_status="in_progress"
        )

        entries = get_audit_for_entity(db_session, "request", req.id)
        assert any(e.action == "request.status_changed" for e in entries)
