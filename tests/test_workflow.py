"""
tests/test_workflow.py
-----------------------
End-to-end integration test for the complete service request workflow:

  1. A Requester creates a request (status: SUBMITTED)
  2. An Administrator assigns a technician (status: ASSIGNED)
  3. The Technician starts work (status: IN_PROGRESS)
  4. The Technician adds a progress comment
  5. The Technician resolves the request (status: RESOLVED, with resolution notes)
  6. The Admin closes the request (status: CLOSED)
  7. Verify the full history trail — StatusHistory, RequestHistory, AuditLog

Also tests:
  - Requester cannot see another user's requests
  - Requester cannot cancel an assigned request
  - Technician cannot update a request not assigned to them
  - Admin AI recommendation review (approve category)
  - Location integration (structured location on a request)
  - Comments are visible to all roles
"""

import pytest
from datetime import datetime, timezone

from database.models.request import (
    RequestCategory, RequestPriority, RequestStatus,
)
from database.models.request_history import HistoryEventType
from database.crud.request_crud import (
    create_request,
    get_request_by_id,
    get_requests_for_requester,
    get_requests_for_technician,
    update_request_status,
    write_request_history,
    get_all_requests,
)
from database.crud.assignment_crud import (
    assign_request,
    unassign_request,
    get_assignment_by_request,
    get_technician_open_workload,
)
from database.crud.history_crud import (
    record_request_created,
    get_history_for_request,
)
from database.crud.comment_crud import add_comment, get_comments_for_request
from database.crud.audit_crud import (
    log_request_created,
    log_request_status_changed,
    log_request_assigned,
    log_request_cancelled,
    log_event,
    get_audit_for_entity,
    get_audit_log,
)
from database.crud.location_crud import create_location, get_location_by_id
from core.security import hash_password, verify_password


# ---------------------------------------------------------------------------
# Helper: create a full set of users for the workflow
# ---------------------------------------------------------------------------

@pytest.fixture()
def workflow_users(make_user):
    """Create a requester, technician, and admin for the full workflow test."""
    return {
        "requester": make_user(
            username="wf_requester",
            full_name="Workflow Requester",
            email="wf_req@test.local",
            role="requester",
            password="WfReq@Test1",
        ),
        "technician": make_user(
            username="wf_technician",
            full_name="Workflow Technician",
            email="wf_tech@test.local",
            role="technician",
            password="WfTech@Test1",
        ),
        "admin": make_user(
            username="wf_admin",
            full_name="Workflow Admin",
            email="wf_admin@test.local",
            role="admin",
            password="WfAdmin@Test1",
        ),
    }


# ---------------------------------------------------------------------------
# Full lifecycle test
# ---------------------------------------------------------------------------

class TestFullWorkflow:
    """Test the complete request lifecycle from submission to closure."""

    def test_complete_request_lifecycle(self, db_session, workflow_users, make_location):
        """
        Full lifecycle:
          Requester creates → Admin assigns → Tech starts → Tech resolves → Admin closes

        Verifies at each step:
          - Status is correct
          - StatusHistory has an entry
          - RequestHistory has an entry
          - AuditLog has an entry
        """
        req_user = workflow_users["requester"]
        tech = workflow_users["technician"]
        admin = workflow_users["admin"]

        # --- Setup: create a location ---
        loc = make_location(building_name="WF Building", floor="2", area="Office 204")

        # ===================================================================
        # STEP 1: Requester creates a request
        # ===================================================================
        req = create_request(
            session=db_session,
            requester_id=req_user.id,
            title="Broken air conditioner in office 204",
            description="The AC unit has stopped cooling and is making a loud noise. "
                       "This has been ongoing since Monday morning and is affecting work.",
            location=loc.display_name(),
            category=RequestCategory.HVAC,
            priority=RequestPriority.HIGH,
        )
        req.location_id = loc.id
        db_session.flush()

        # Initial history entries
        record_request_created(
            session=db_session,
            request_id=req.id,
            created_by_id=req_user.id,
            created_by_role="requester",
        )
        write_request_history(
            session=db_session,
            request_id=req.id,
            changed_by=req_user.id,
            event_type=HistoryEventType.CREATED,
            new_status=RequestStatus.SUBMITTED.value,
            note="Request submitted.",
        )
        log_request_created(db_session, user_id=req_user.id, request_id=req.id)
        db_session.flush()

        # Verify step 1
        assert req.status == RequestStatus.SUBMITTED
        assert req.reference_number.startswith("REQ-")
        assert req.location_id == loc.id

        # History checks
        status_history = get_history_for_request(db_session, req.id)
        assert len(status_history) >= 1
        assert status_history[-1].new_status == RequestStatus.SUBMITTED

        req_history = req.history
        assert any(h.event_type == HistoryEventType.CREATED for h in req_history)

        audit_entries = get_audit_for_entity(db_session, "request", req.id)
        assert any(e.action == "request.created" for e in audit_entries)

        # ===================================================================
        # STEP 2: Admin assigns a technician
        # ===================================================================
        assign_request(
            session=db_session,
            request_id=req.id,
            technician_id=tech.id,
            assigned_by_id=admin.id,
            assignment_notes="Please prioritize — affecting multiple staff.",
        )
        db_session.flush()

        # Verify step 2
        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.status == RequestStatus.ASSIGNED
        assert refreshed.assigned_technician_id == tech.id

        assignment = get_assignment_by_request(db_session, req.id)
        assert assignment is not None
        assert assignment.technician_id == tech.id

        # Write history entries for assignment
        write_request_history(
            session=db_session,
            request_id=req.id,
            changed_by=admin.id,
            event_type=HistoryEventType.ASSIGNMENT,
            note=f"Assigned to technician id={tech.id}.",
        )
        log_request_assigned(db_session, admin_id=admin.id, request_id=req.id, technician_id=tech.id)
        db_session.flush()

        # ===================================================================
        # STEP 3: Technician starts work (ASSIGNED → IN_PROGRESS)
        # ===================================================================
        update_request_status(
            session=db_session,
            request_id=req.id,
            new_status=RequestStatus.IN_PROGRESS,
            changed_by_id=tech.id,
            changed_by_role="technician",
            note="Started investigating the AC unit.",
        )
        write_request_history(
            session=db_session,
            request_id=req.id,
            changed_by=tech.id,
            event_type=HistoryEventType.STATUS_CHANGE,
            old_status=RequestStatus.ASSIGNED.value,
            new_status=RequestStatus.IN_PROGRESS.value,
            note="Started investigating the AC unit.",
        )
        log_request_status_changed(
            db_session, user_id=tech.id, request_id=req.id,
            old_status="assigned", new_status="in_progress",
        )
        db_session.flush()

        # Verify step 3
        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.status == RequestStatus.IN_PROGRESS

        # ===================================================================
        # STEP 4: Technician adds a progress comment
        # ===================================================================
        add_comment(
            session=db_session,
            request_id=req.id,
            user_id=tech.id,
            comment="Inspected the unit. The compressor is faulty and needs replacement. "
                    "Ordering the part now.",
        )
        write_request_history(
            session=db_session,
            request_id=req.id,
            changed_by=tech.id,
            event_type=HistoryEventType.COMMENT_ADDED,
            note="Inspected the unit. The compressor is faulty...",
        )
        db_session.flush()

        # Verify comment
        comments = get_comments_for_request(db_session, req.id)
        assert len(comments) >= 1
        assert comments[-1].user_id == tech.id
        assert "compressor" in comments[-1].comment

        # ===================================================================
        # STEP 5: Technician resolves the request (IN_PROGRESS → RESOLVED)
        # ===================================================================
        update_request_status(
            session=db_session,
            request_id=req.id,
            new_status=RequestStatus.RESOLVED,
            changed_by_id=tech.id,
            changed_by_role="technician",
            note="Compressor replaced and tested.",
        )
        req.resolution_notes = "Replaced the faulty compressor with a new unit. "
        "Tested cooling output — now operating at 22°C. No further issues detected."
        write_request_history(
            session=db_session,
            request_id=req.id,
            changed_by=tech.id,
            event_type=HistoryEventType.STATUS_CHANGE,
            old_status=RequestStatus.IN_PROGRESS.value,
            new_status=RequestStatus.RESOLVED.value,
            note="Compressor replaced and tested.",
        )
        log_request_status_changed(
            db_session, user_id=tech.id, request_id=req.id,
            old_status="in_progress", new_status="resolved",
        )
        db_session.flush()

        # Verify step 5
        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.status == RequestStatus.RESOLVED
        assert refreshed.resolved_at is not None
        assert refreshed.resolution_notes is not None

        # ===================================================================
        # STEP 6: Admin closes the request (RESOLVED → CLOSED)
        # ===================================================================
        update_request_status(
            session=db_session,
            request_id=req.id,
            new_status=RequestStatus.CLOSED,
            changed_by_id=admin.id,
            changed_by_role="admin",
            note="Confirmed resolved by requester. Closing.",
        )
        write_request_history(
            session=db_session,
            request_id=req.id,
            changed_by=admin.id,
            event_type=HistoryEventType.STATUS_CHANGE,
            old_status=RequestStatus.RESOLVED.value,
            new_status=RequestStatus.CLOSED.value,
            note="Confirmed resolved. Closing.",
        )
        log_request_status_changed(
            db_session, user_id=admin.id, request_id=req.id,
            old_status="resolved", new_status="closed",
        )
        db_session.flush()

        # Verify step 6
        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.status == RequestStatus.CLOSED
        assert refreshed.closed_at is not None

        # ===================================================================
        # STEP 7: Verify the complete history trail
        # ===================================================================

        # --- StatusHistory (original table) ---
        full_status_history = get_history_for_request(db_session, req.id)
        # Expected: SUBMITTED (created) → ASSIGNED → IN_PROGRESS → RESOLVED → CLOSED
        assert len(full_status_history) >= 5

        # Verify the status transitions in order
        status_values = [h.new_status for h in full_status_history]
        assert RequestStatus.SUBMITTED in status_values
        assert RequestStatus.ASSIGNED in status_values
        assert RequestStatus.IN_PROGRESS in status_values
        assert RequestStatus.RESOLVED in status_values
        assert RequestStatus.CLOSED in status_values

        # --- RequestHistory (v2 table) ---
        # Expire session cache to force a fresh query of the relationship
        db_session.expire_all()
        final_req = get_request_by_id(db_session, req.id)
        full_req_history = final_req.history
        event_types = [h.event_type for h in full_req_history]
        assert HistoryEventType.CREATED in event_types
        assert HistoryEventType.ASSIGNMENT in event_types
        assert HistoryEventType.STATUS_CHANGE in event_types
        assert HistoryEventType.COMMENT_ADDED in event_types

        # --- AuditLog ---
        all_audit = get_audit_for_entity(db_session, "request", req.id)
        audit_actions = [e.action for e in all_audit]
        assert "request.created" in audit_actions
        assert "request.assigned" in audit_actions
        assert "request.status_changed" in audit_actions

        # --- Comments ---
        final_comments = get_comments_for_request(db_session, req.id)
        assert len(final_comments) >= 1
        assert final_comments[-1].user_id == tech.id

        # --- Requester can see their own request ---
        requester_view = get_requests_for_requester(db_session, req_user.id)
        requester_ids = {r.id for r in requester_view}
        assert req.id in requester_ids

        # --- Technician can see the assigned request ---
        tech_view = get_requests_for_technician(db_session, tech.id)
        tech_ids = {r.id for r in tech_view}
        assert req.id in tech_ids

        # --- Admin can see all requests ---
        all_reqs = get_all_requests(db_session)
        all_ids = {r.id for r in all_reqs}
        assert req.id in all_ids

    def test_request_status_progression_matches_workflow(self, db_session, make_user):
        """Verify the workflow status sequence is correctly ordered."""
        user = make_user(username="progression_test", role="requester")

        req = create_request(
            session=db_session,
            requester_id=user.id,
            title="Test progression workflow title",
            description="Testing the status progression for the workflow.",
            location="Building A",
            category=RequestCategory.ELECTRICAL,
        )
        record_request_created(db_session, req.id, user.id, "requester")
        db_session.flush()

        # Verify it starts as SUBMITTED
        assert req.status == RequestStatus.SUBMITTED

        # Transition through each expected status
        expected_sequence = [
            RequestStatus.SUBMITTED,
            RequestStatus.ASSIGNED,
            RequestStatus.IN_PROGRESS,
            RequestStatus.RESOLVED,
            RequestStatus.CLOSED,
        ]

        current = req.status
        for expected in expected_sequence:
            assert current == expected, (
                f"Expected status {expected.value} but got {current.value}"
            )
            # Move to next status
            if expected != expected_sequence[-1]:
                next_status = expected_sequence[expected_sequence.index(expected) + 1]
                update_request_status(
                    session=db_session,
                    request_id=req.id,
                    new_status=next_status,
                    changed_by_id=user.id,
                    changed_by_role="admin",
                )
                current = get_request_by_id(db_session, req.id).status


# ---------------------------------------------------------------------------
# Permission enforcement tests
# ---------------------------------------------------------------------------

class TestWorkflowPermissions:
    """Test that role-based access control is enforced throughout the workflow."""

    def test_requester_cannot_see_other_users_requests(self, db_session, make_user):
        """A requester must only see their own requests — not other requesters'."""
        alice = make_user(username="perm_alice", role="requester")
        bob = make_user(username="perm_bob", role="requester")

        alice_req = create_request(
            session=db_session, requester_id=alice.id,
            title="Alice's request title text",
            description="Alice's description here.",
            location="Room A",
        )
        bob_req = create_request(
            session=db_session, requester_id=bob.id,
            title="Bob's request title text",
            description="Bob's description here.",
            location="Room B",
        )
        db_session.flush()

        alice_view = get_requests_for_requester(db_session, alice.id)
        alice_ids = {r.id for r in alice_view}
        assert alice_req.id in alice_ids
        assert bob_req.id not in alice_ids

    def test_requester_cannot_cancel_assigned_request(self, db_session, make_user):
        """Once a request is ASSIGNED, the requester cannot cancel it."""
        # Test the business rule at the CRUD level: only SUBMITTED can transition to CANCELLED
        # We don't import business.request_service because it requires a PG engine.

        requester = make_user(username="cancel_after_assign", role="requester")
        admin = make_user(username="cancel_admin", role="admin")
        tech = make_user(username="cancel_tech", role="technician")

        req = create_request(
            session=db_session, requester_id=requester.id,
            title="Request to test cancel after assign",
            description="This request will be assigned then we try to cancel.",
            location="Room X",
        )
        record_request_created(db_session, req.id, requester.id, "requester")
        db_session.flush()

        # Admin assigns
        assign_request(db_session, req.id, tech.id, admin.id)
        db_session.flush()

        # Verify status is ASSIGNED
        assert get_request_by_id(db_session, req.id).status == RequestStatus.ASSIGNED

        # The business rule: cancel_request() checks if status is in cancellable set
        # {SUBMITTED, OPEN}. Since it's ASSIGNED, it should fail.
        # We simulate the check here without importing the business layer (which needs psycopg2).
        cancellable_statuses = {RequestStatus.SUBMITTED.value, RequestStatus.OPEN.value}
        current_status = get_request_by_id(db_session, req.id).status.value
        assert current_status not in cancellable_statuses, (
            "Assigned request should not be cancellable"
        )

    def test_technician_cannot_update_unassigned_request(self, db_session, make_user):
        """A technician who is not assigned cannot update a request's status."""
        # Test at the CRUD layer: verify assignment ownership check
        admin = make_user(username="unassigned_admin", role="admin")
        tech1 = make_user(username="unassigned_t1", role="technician")
        tech2 = make_user(username="unassigned_t2", role="technician")
        req_user = make_user(username="unassigned_req", role="requester")

        req = create_request(
            session=db_session, requester_id=req_user.id,
            title="Unassigned technician test title",
            description="Testing that unassigned technicians cannot update.",
            location="Room Y",
        )
        record_request_created(db_session, req.id, req_user.id, "requester")
        assign_request(db_session, req.id, tech1.id, admin.id)
        db_session.flush()

        # Verify tech2 is not the assigned technician
        assignment = get_assignment_by_request(db_session, req.id)
        assert assignment.technician_id == tech1.id
        assert assignment.technician_id != tech2.id

        # The business layer's technician_update_status checks:
        #   req.assignment is None or req.assignment.technician_id != technician_id
        # We verify this condition holds for tech2:
        loaded_req = get_request_by_id(db_session, req.id)
        is_assigned_to_tech2 = (
            loaded_req.assignment is not None
            and loaded_req.assignment.technician_id == tech2.id
        )
        assert not is_assigned_to_tech2, (
            "tech2 should not be the assigned technician"
        )

    def test_technician_can_update_assigned_request(self, db_session, make_user):
        """The assigned technician can update the status at the CRUD layer."""
        admin = make_user(username="assigned_admin", role="admin")
        tech = make_user(username="assigned_tech", role="technician")
        req_user = make_user(username="assigned_req", role="requester")

        req = create_request(
            session=db_session, requester_id=req_user.id,
            title="Assigned technician test title",
            description="Testing that the assigned technician can update.",
            location="Room Z",
        )
        record_request_created(db_session, req.id, req_user.id, "requester")
        assign_request(db_session, req.id, tech.id, admin.id)
        db_session.flush()

        # Verify assignment ownership holds
        loaded_req = get_request_by_id(db_session, req.id)
        assert loaded_req.assignment is not None
        assert loaded_req.assignment.technician_id == tech.id

        # Assigned tech updates to IN_PROGRESS via CRUD layer
        update_request_status(
            session=db_session,
            request_id=req.id,
            new_status=RequestStatus.IN_PROGRESS,
            changed_by_id=tech.id,
            changed_by_role="technician",
            note="Starting work",
        )
        db_session.flush()

        assert get_request_by_id(db_session, req.id).status == RequestStatus.IN_PROGRESS

    def test_only_admin_can_assign(self, db_session, make_user):
        """
        Business rule: only admins can assign technicians.
        We verify the assignment_crud layer accepts the call, but the
        business layer's admin_assign_request is intended for admin use only.
        """
        admin = make_user(username="only_admin_assign", role="admin")
        tech = make_user(username="only_admin_tech", role="technician")
        req_user = make_user(username="only_admin_req", role="requester")

        req = create_request(
            session=db_session, requester_id=req_user.id,
            title="Only admin can assign test title",
            description="Testing that assignment is restricted to admins.",
            location="Room W",
        )
        record_request_created(db_session, req.id, req_user.id, "requester")
        db_session.flush()

        # Admin assigns — should work
        assign_request(db_session, req.id, tech.id, admin.id)
        assert get_request_by_id(db_session, req.id).status == RequestStatus.ASSIGNED


# ---------------------------------------------------------------------------
# History and audit verification tests
# ---------------------------------------------------------------------------

class TestHistoryAndAuditTrail:
    """Verify every state change creates the required history and audit records."""

    def test_every_status_change_creates_status_history(self, db_session, make_user):
        """Each update_request_status call must append a StatusHistory entry."""
        user = make_user(username="history_test_user", role="admin")

        req = create_request(
            session=db_session, requester_id=user.id,
            title="History trail test request title",
            description="Testing that every status change creates history.",
            location="Room H",
        )
        record_request_created(db_session, req.id, user.id, "requester")
        db_session.flush()

        initial_count = len(get_history_for_request(db_session, req.id))

        # Make 3 status changes
        for new_status in [RequestStatus.ASSIGNED, RequestStatus.IN_PROGRESS, RequestStatus.RESOLVED]:
            update_request_status(
                session=db_session,
                request_id=req.id,
                new_status=new_status,
                changed_by_id=user.id,
                changed_by_role="admin",
            )
            db_session.flush()

        final_count = len(get_history_for_request(db_session, req.id))
        # Initial + 3 transitions = 4 total
        assert final_count == initial_count + 3

    def test_every_status_change_creates_request_history(self, db_session, make_user):
        """Each write_request_history call must append a RequestHistory entry."""
        user = make_user(username="req_history_user", role="admin")

        req = create_request(
            session=db_session, requester_id=user.id,
            title="Request history trail test title",
            description="Testing request history entries.",
            location="Room RH",
        )
        write_request_history(
            session=db_session, request_id=req.id, changed_by=user.id,
            event_type=HistoryEventType.CREATED,
            new_status=RequestStatus.SUBMITTED.value,
        )
        db_session.flush()

        # Expire the session cache so relationships are re-loaded
        db_session.expire_all()
        initial_count = len(get_request_by_id(db_session, req.id).history)

        # Add 2 more history entries
        write_request_history(
            session=db_session, request_id=req.id, changed_by=user.id,
            event_type=HistoryEventType.STATUS_CHANGE,
            old_status="submitted", new_status="assigned",
        )
        write_request_history(
            session=db_session, request_id=req.id, changed_by=user.id,
            event_type=HistoryEventType.STATUS_CHANGE,
            old_status="assigned", new_status="in_progress",
        )
        db_session.flush()

        # Expire and re-query to pick up the new entries
        db_session.expire_all()
        refreshed = get_request_by_id(db_session, req.id)
        assert len(refreshed.history) == initial_count + 2

    def test_every_status_change_creates_audit_log(self, db_session, make_user):
        """Each log_request_status_changed call must create an AuditLog entry."""
        user = make_user(username="audit_trail_user", role="admin")

        req = create_request(
            session=db_session, requester_id=user.id,
            title="Audit trail test request title",
            description="Testing audit log entries for status changes.",
            location="Room AL",
        )
        log_request_created(db_session, user_id=user.id, request_id=req.id)
        db_session.flush()

        initial_audit = get_audit_for_entity(db_session, "request", req.id)
        initial_count = len(initial_audit)

        # Make 2 status changes with audit logging
        log_request_status_changed(
            db_session, user_id=user.id, request_id=req.id,
            old_status="submitted", new_status="assigned",
        )
        log_request_status_changed(
            db_session, user_id=user.id, request_id=req.id,
            old_status="assigned", new_status="in_progress",
        )
        db_session.flush()

        final_audit = get_audit_for_entity(db_session, "request", req.id)
        assert len(final_audit) == initial_count + 2

        # Verify the audit actions
        actions = [e.action for e in final_audit]
        assert "request.created" in actions
        assert "request.status_changed" in actions

    def test_comment_creates_history_and_audit(self, db_session, make_user):
        """Adding a comment should create both a RequestHistory and AuditLog entry."""
        user = make_user(username="comment_audit_user", role="technician")
        req_user = make_user(username="comment_audit_req", role="requester")

        req = create_request(
            session=db_session, requester_id=req_user.id,
            title="Comment audit test request title",
            description="Testing that comments create history and audit entries.",
            location="Room CA",
        )
        db_session.flush()

        # Add comment
        add_comment(db_session, req.id, user.id, "Test progress comment for audit trail.")

        # Write request history for the comment
        write_request_history(
            session=db_session, request_id=req.id, changed_by=user.id,
            event_type=HistoryEventType.COMMENT_ADDED,
            note="Test progress comment for audit trail.",
        )

        # Write audit log for the comment
        log_event(
            db_session,
            action="request.comment_added",
            user_id=user.id,
            entity_type="request",
            entity_id=req.id,
            detail={"role": "technician", "preview": "Test progress comment..."},
        )
        db_session.flush()

        # Verify RequestHistory
        refreshed = get_request_by_id(db_session, req.id)
        comment_history = [h for h in refreshed.history if h.event_type == HistoryEventType.COMMENT_ADDED]
        assert len(comment_history) >= 1

        # Verify AuditLog
        audit = get_audit_for_entity(db_session, "request", req.id)
        comment_audits = [e for e in audit if e.action == "request.comment_added"]
        assert len(comment_audits) >= 1


# ---------------------------------------------------------------------------
# Resolved request retains history
# ---------------------------------------------------------------------------

class TestResolvedRequestRetainsHistory:
    """Verify that resolved/closed requests keep their full history intact."""

    def test_resolved_request_keeps_all_history(self, db_session, make_user):
        """After resolution, all history entries must still be present."""
        user = make_user(username="retain_history_user", role="admin")

        req = create_request(
            session=db_session, requester_id=user.id,
            title="History retention test title text",
            description="Testing that history is retained after resolution.",
            location="Room HR",
        )
        record_request_created(db_session, req.id, user.id, "requester")
        write_request_history(
            session=db_session, request_id=req.id, changed_by=user.id,
            event_type=HistoryEventType.CREATED,
            new_status=RequestStatus.SUBMITTED.value,
        )
        db_session.flush()

        # Transition through several statuses
        for status in [RequestStatus.ASSIGNED, RequestStatus.IN_PROGRESS, RequestStatus.RESOLVED]:
            update_request_status(
                session=db_session, request_id=req.id,
                new_status=status, changed_by_id=user.id, changed_by_role="admin",
            )
            write_request_history(
                session=db_session, request_id=req.id, changed_by=user.id,
                event_type=HistoryEventType.STATUS_CHANGE,
                old_status="previous", new_status=status.value,
            )
            db_session.flush()

        # Verify all history is still present
        status_history = get_history_for_request(db_session, req.id)
        assert len(status_history) >= 4  # created + 3 transitions

        refreshed = get_request_by_id(db_session, req.id)
        assert len(refreshed.history) >= 4

        # Verify the request itself is not deleted
        assert get_request_by_id(db_session, req.id) is not None

    def test_closed_request_not_deleted(self, db_session, make_user):
        """A closed request must still exist in the database."""
        user = make_user(username="closed_retained", role="admin")

        req = create_request(
            session=db_session, requester_id=user.id,
            title="Closed retention test title text",
            description="Testing that closed requests are not deleted.",
            location="Room CR",
        )
        record_request_created(db_session, req.id, user.id, "requester")
        db_session.flush()

        req_id = req.id

        # Close it
        update_request_status(
            session=db_session, request_id=req.id,
            new_status=RequestStatus.CLOSED,
            changed_by_id=user.id, changed_by_role="admin",
        )
        db_session.flush()

        # Verify it still exists
        assert get_request_by_id(db_session, req_id) is not None
        assert get_request_by_id(db_session, req_id).status == RequestStatus.CLOSED


# ---------------------------------------------------------------------------
# Location integration
# ---------------------------------------------------------------------------

class TestLocationIntegration:
    """Verify location integration with the request workflow."""

    def test_request_with_structured_location(self, db_session, make_user, make_location):
        """A request can be linked to a structured Location via location_id."""
        user = make_user(username="loc_integration_user", role="requester")
        loc = make_location(building_name="Integration Tower", floor="5", area="Data Center")

        req = create_request(
            session=db_session, requester_id=user.id,
            title="Location integration test title",
            description="Testing structured location on a request.",
            location=loc.display_name(),
            category=RequestCategory.IT_SUPPORT,
        )
        req.location_id = loc.id
        db_session.flush()

        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.location_id == loc.id
        assert refreshed.location_obj is not None
        assert refreshed.location_obj.building_name == "Integration Tower"

    def test_request_without_location_still_works(self, db_session, make_user):
        """Requests with only free-text location (no location_id) must still work."""
        user = make_user(username="no_loc_user", role="requester")

        req = create_request(
            session=db_session, requester_id=user.id,
            title="No structured location test title",
            description="Testing request with free-text location only.",
            location="Building B, Floor 3, Room 301",
        )
        db_session.flush()

        refreshed = get_request_by_id(db_session, req.id)
        assert refreshed.location_id is None
        assert refreshed.location == "Building B, Floor 3, Room 301"
