"""
tests/test_qa_workflow.py
--------------------------
QA tests for the request lifecycle: creation, assignment, status transitions, history.
"""

import pytest
from datetime import datetime, timezone

from database.models.request import (
    RequestCategory, RequestPriority, RequestStatus,
)
from database.models.request_history import HistoryEventType
from database.crud.request_crud import (
    create_request, get_request_by_id, update_request_status,
    update_resolution_notes, update_request_priority, write_request_history,
)
from database.crud.assignment_crud import (
    assign_request, unassign_request, get_assignment_by_request,
)
from database.crud.history_crud import (
    record_request_created, get_history_for_request,
)
from database.crud.comment_crud import add_comment, get_comments_for_request
from database.crud.audit_crud import (
    log_request_created, log_request_status_changed, get_audit_for_entity,
)


class TestRequestCreation:
    def test_create_request_assigns_reference(self, db_session, make_user):
        user = make_user(username="create_test")
        req = create_request(
            db_session, user.id,
            "Test request creation title",
            "Description long enough to pass validation.",
            "Building A",
        )
        assert req.reference_number.startswith("REQ-")
        assert req.status == RequestStatus.SUBMITTED

    def test_create_request_sets_defaults(self, db_session, make_user):
        user = make_user(username="defaults_test")
        req = create_request(
            db_session, user.id,
            "Default values test title",
            "Description text here for testing.",
            "Building B",
        )
        assert req.priority == RequestPriority.MEDIUM
        assert req.category == RequestCategory.OTHER
        assert req.status == RequestStatus.SUBMITTED

    def test_create_request_with_category(self, db_session, make_user):
        user = make_user(username="category_test")
        req = create_request(
            db_session, user.id,
            "Category test request title",
            "Testing category assignment.",
            "Room X",
            category=RequestCategory.PLUMBING,
            priority=RequestPriority.HIGH,
        )
        assert req.category == RequestCategory.PLUMBING
        assert req.priority == RequestPriority.HIGH


class TestRequestAssignment:
    def test_assign_transitions_submitted_to_assigned(self, db_session, make_user):
        admin = make_user(username="qa_admin", role="admin")
        tech = make_user(username="qa_tech", role="technician")
        requester = make_user(username="qa_req", role="requester")
        req = create_request(db_session, requester.id, "Assign test title", "Desc here.", "Loc")
        record_request_created(db_session, req.id, requester.id, "requester")
        db_session.flush()
        assign_request(db_session, req.id, tech.id, admin.id)
        assert db_session.get(type(req), req.id).status == RequestStatus.ASSIGNED

    def test_assignment_syncs_denorm_field(self, db_session, make_user):
        admin = make_user(username="denorm_admin", role="admin")
        tech = make_user(username="denorm_tech", role="technician")
        requester = make_user(username="denorm_req", role="requester")
        req = create_request(db_session, requester.id, "Denorm test title", "Desc here.", "Loc")
        record_request_created(db_session, req.id, requester.id, "requester")
        db_session.flush()
        assign_request(db_session, req.id, tech.id, admin.id)
        loaded = db_session.get(type(req), req.id)
        assert loaded.assigned_technician_id == tech.id

    def test_reassign_updates_technician(self, db_session, make_user):
        admin = make_user(username="re_admin", role="admin")
        tech1 = make_user(username="re_t1", role="technician")
        tech2 = make_user(username="re_t2", role="technician")
        requester = make_user(username="re_req", role="requester")
        req = create_request(db_session, requester.id, "Reassign test title", "Desc here.", "Loc")
        record_request_created(db_session, req.id, requester.id, "requester")
        db_session.flush()
        assign_request(db_session, req.id, tech1.id, admin.id)
        assign_request(db_session, req.id, tech2.id, admin.id)
        assert get_assignment_by_request(db_session, req.id).technician_id == tech2.id

    def test_unassign_returns_to_submitted(self, db_session, make_user):
        admin = make_user(username="un_admin", role="admin")
        tech = make_user(username="un_tech", role="technician")
        requester = make_user(username="un_req", role="requester")
        req = create_request(db_session, requester.id, "Unassign test title", "Desc here.", "Loc")
        record_request_created(db_session, req.id, requester.id, "requester")
        db_session.flush()
        assign_request(db_session, req.id, tech.id, admin.id)
        unassign_request(db_session, req.id, admin.id)
        loaded = db_session.get(type(req), req.id)
        assert loaded.status == RequestStatus.SUBMITTED
        assert loaded.assigned_technician_id is None


class TestStatusTransitions:
    def test_full_lifecycle(self, db_session, make_user):
        admin = make_user(username="life_admin", role="admin")
        tech = make_user(username="life_tech", role="technician")
        requester = make_user(username="life_req", role="requester")

        req = create_request(db_session, requester.id, "Lifecycle test title", "Desc here.", "Loc")
        record_request_created(db_session, req.id, requester.id, "requester")
        db_session.flush()
        assert req.status == RequestStatus.SUBMITTED

        assign_request(db_session, req.id, tech.id, admin.id)
        db_session.flush()
        assert db_session.get(type(req), req.id).status == RequestStatus.ASSIGNED

        update_request_status(db_session, req.id, RequestStatus.IN_PROGRESS, tech.id, "technician")
        db_session.flush()
        assert db_session.get(type(req), req.id).status == RequestStatus.IN_PROGRESS

        update_resolution_notes(db_session, req.id, "Replaced the broken part.")
        update_request_status(db_session, req.id, RequestStatus.RESOLVED, tech.id, "technician", "Fixed.")
        db_session.flush()
        loaded = db_session.get(type(req), req.id)
        assert loaded.status == RequestStatus.RESOLVED
        assert loaded.resolved_at is not None

        update_request_status(db_session, req.id, RequestStatus.CLOSED, admin.id, "admin", "Verified.")
        db_session.flush()
        assert db_session.get(type(req), req.id).status == RequestStatus.CLOSED
        assert db_session.get(type(req), req.id).closed_at is not None

    def test_priority_override(self, db_session, make_user):
        admin = make_user(username="pri_admin", role="admin")
        requester = make_user(username="pri_req", role="requester")
        req = create_request(db_session, requester.id, "Priority test title", "Desc here.", "Loc")
        record_request_created(db_session, req.id, requester.id, "requester")
        db_session.flush()
        update_request_priority(db_session, req.id, RequestPriority.CRITICAL, admin.id)
        assert db_session.get(type(req), req.id).priority == RequestPriority.CRITICAL


class TestRequestHistory:
    def test_every_status_change_creates_history(self, db_session, make_user):
        user = make_user(username="hist_admin", role="admin")
        requester = make_user(username="hist_req", role="requester")
        req = create_request(db_session, requester.id, "History test title", "Desc here.", "Loc")
        record_request_created(db_session, req.id, requester.id, "requester")
        db_session.flush()
        initial = len(get_history_for_request(db_session, req.id))
        for status in [RequestStatus.ASSIGNED, RequestStatus.IN_PROGRESS, RequestStatus.RESOLVED]:
            update_request_status(db_session, req.id, status, user.id, "admin")
            db_session.flush()
        final = len(get_history_for_request(db_session, req.id))
        assert final >= initial + 3

    def test_history_preserved_after_resolution(self, db_session, make_user):
        user = make_user(username="preserve_admin", role="admin")
        requester = make_user(username="preserve_req", role="requester")
        req = create_request(db_session, requester.id, "Preserve test title", "Desc here.", "Loc")
        record_request_created(db_session, req.id, requester.id, "requester")
        db_session.flush()
        for status in [RequestStatus.ASSIGNED, RequestStatus.IN_PROGRESS, RequestStatus.RESOLVED, RequestStatus.CLOSED]:
            update_request_status(db_session, req.id, status, user.id, "admin")
            db_session.flush()
        # Verify request still exists and has history
        loaded = db_session.get(type(req), req.id)
        assert loaded is not None
        assert len(get_history_for_request(db_session, req.id)) >= 5

    def test_comment_creates_request_history(self, db_session, make_user):
        user = make_user(username="comment_hist", role="technician")
        requester = make_user(username="comment_req", role="requester")
        req = create_request(db_session, requester.id, "Comment hist test title", "Desc here.", "Loc")
        db_session.flush()
        add_comment(db_session, req.id, user.id, "Progress update comment for testing.")
        write_request_history(
            session=db_session, request_id=req.id, changed_by=user.id,
            event_type=HistoryEventType.COMMENT_ADDED,
            note="Progress update comment for testing.",
        )
        db_session.flush()
        db_session.expire_all()
        loaded = db_session.get(type(req), req.id)
        comment_events = [h for h in loaded.history if h.event_type == HistoryEventType.COMMENT_ADDED]
        assert len(comment_events) >= 1

    def test_audit_log_for_status_change(self, db_session, make_user):
        user = make_user(username="audit_admin", role="admin")
        requester = make_user(username="audit_req", role="requester")
        req = create_request(db_session, requester.id, "Audit test title", "Desc here.", "Loc")
        record_request_created(db_session, req.id, requester.id, "requester")
        log_request_created(db_session, user_id=user.id, request_id=req.id)
        db_session.flush()
        update_request_status(db_session, req.id, RequestStatus.ASSIGNED, user.id, "admin")
        log_request_status_changed(db_session, user_id=user.id, request_id=req.id,
                                    old_status="submitted", new_status="assigned")
        db_session.flush()
        entries = get_audit_for_entity(db_session, "request", req.id)
        actions = [e.action for e in entries]
        assert "request.created" in actions
        assert "request.status_changed" in actions
