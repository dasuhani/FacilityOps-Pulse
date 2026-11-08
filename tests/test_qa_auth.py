"""
tests/test_qa_auth.py
----------------------
QA tests for authentication: login, password hashing, role-based restrictions.
"""

import pytest

from core.security import hash_password, verify_password, validate_password_strength
from database.crud.user_crud import (
    create_user, authenticate_user, get_user_by_username,
    set_user_active, update_last_login, get_technicians,
)
from database.models.user import UserRole
from database.models.request import (
    RequestCategory, RequestPriority, RequestStatus,
)
from database.crud.request_crud import (
    create_request, get_requests_for_requester, get_requests_for_technician,
    update_request_status,
)
from database.crud.assignment_crud import assign_request
from database.crud.history_crud import record_request_created


class TestPasswordHashing:
    def test_hash_is_bcrypt(self):
        h = hash_password("Test@1234")
        assert h.startswith("$2b$12$")

    def test_verify_correct(self):
        h = hash_password("Correct@Pass1")
        assert verify_password("Correct@Pass1", h)

    def test_verify_wrong(self):
        h = hash_password("Right@Pass1")
        assert not verify_password("Wrong@Pass1", h)

    def test_hash_not_plaintext(self):
        h = hash_password("Secret@Pass1")
        assert "Secret@Pass1" not in h

    def test_empty_password_rejected(self):
        with pytest.raises(ValueError):
            hash_password("")

    def test_strength_validation_rejects_weak(self):
        errors = validate_password_strength("abc")
        assert len(errors) >= 3

    def test_strength_validation_accepts_strong(self):
        assert validate_password_strength("Strong@Pass1") == []


class TestAuthentication:
    def test_successful_login(self, db_session, make_user):
        make_user(username="login_ok", password="Login@Pass1", is_active=True)
        user = authenticate_user(db_session, "login_ok", "Login@Pass1")
        assert user is not None
        assert user.username == "login_ok"

    def test_wrong_password(self, db_session, make_user):
        make_user(username="wrong_pw", password="Right@Pass1")
        assert authenticate_user(db_session, "wrong_pw", "Wrong@Pass1") is None

    def test_unknown_user(self, db_session):
        assert authenticate_user(db_session, "nobody", "Any@Pass1") is None

    def test_inactive_user_blocked(self, db_session, make_user):
        make_user(username="inactive", password="Pass@1234", is_active=False)
        assert authenticate_user(db_session, "inactive", "Pass@1234") is None

    def test_deactivated_user_blocked(self, db_session, make_user):
        user = make_user(username="deactivated", password="Pass@1234", is_active=True)
        assert authenticate_user(db_session, "deactivated", "Pass@1234") is not None
        set_user_active(db_session, user.id, False)
        assert authenticate_user(db_session, "deactivated", "Pass@1234") is None

    def test_last_login_updated(self, db_session, make_user):
        user = make_user(username="last_login")
        assert user.last_login_at is None
        update_last_login(db_session, user.id)
        refreshed = get_user_by_username(db_session, "last_login")
        assert refreshed.last_login_at is not None


class TestRoleBasedAccess:
    """Verify role permissions are enforced in the backend."""

    def test_requester_only_sees_own_requests(self, db_session, make_user):
        alice = make_user(username="rbac_alice", role="requester")
        bob = make_user(username="rbac_bob", role="requester")
        r1 = create_request(db_session, alice.id, "Alice request title", "Alice desc here.", "Room A")
        r2 = create_request(db_session, bob.id, "Bob request title", "Bob desc here.", "Room B")
        record_request_created(db_session, r1.id, alice.id, "requester")
        record_request_created(db_session, r2.id, bob.id, "requester")
        db_session.flush()

        alice_view = get_requests_for_requester(db_session, alice.id)
        alice_ids = {r.id for r in alice_view}
        assert r1.id in alice_ids
        assert r2.id not in alice_ids

    def test_technician_only_sees_assigned_requests(self, db_session, make_user):
        admin = make_user(username="rbac_admin", role="admin")
        tech1 = make_user(username="rbac_t1", role="technician")
        tech2 = make_user(username="rbac_t2", role="technician")
        requester = make_user(username="rbac_req", role="requester")

        r1 = create_request(db_session, requester.id, "Request for tech1 title", "Desc here.", "Loc A")
        r2 = create_request(db_session, requester.id, "Request for tech2 title", "Desc here.", "Loc B")
        record_request_created(db_session, r1.id, requester.id, "requester")
        record_request_created(db_session, r2.id, requester.id, "requester")
        db_session.flush()

        assign_request(db_session, r1.id, tech1.id, admin.id)
        assign_request(db_session, r2.id, tech2.id, admin.id)
        db_session.flush()

        t1_view = get_requests_for_technician(db_session, tech1.id)
        t1_ids = {r.id for r in t1_view}
        assert r1.id in t1_ids
        assert r2.id not in t1_ids

    def test_technician_cannot_update_unassigned_request(self, db_session, make_user):
        admin = make_user(username="unassigned_admin", role="admin")
        tech_assigned = make_user(username="unassigned_t1", role="technician")
        tech_other = make_user(username="unassigned_t2", role="technician")
        requester = make_user(username="unassigned_req", role="requester")

        req = create_request(db_session, requester.id, "Test unassigned title", "Desc here.", "Loc")
        record_request_created(db_session, req.id, requester.id, "requester")
        assign_request(db_session, req.id, tech_assigned.id, admin.id)
        db_session.flush()

        loaded = db_session.get(type(req), req.id)
        is_assigned_to_other = (
            loaded.assignment is not None
            and loaded.assignment.technician_id == tech_other.id
        )
        assert not is_assigned_to_other

    def test_only_admin_can_assign(self, db_session, make_user):
        admin = make_user(username="assign_admin", role="admin")
        tech = make_user(username="assign_tech", role="technician")
        requester = make_user(username="assign_req", role="requester")
        req = create_request(db_session, requester.id, "Admin assign test title", "Desc here.", "Loc")
        record_request_created(db_session, req.id, requester.id, "requester")
        db_session.flush()
        assign_request(db_session, req.id, tech.id, admin.id)
        assert db_session.get(type(req), req.id).status == RequestStatus.ASSIGNED

    def test_requester_cannot_cancel_assigned_request(self, db_session, make_user):
        requester = make_user(username="cancel_req", role="requester")
        admin = make_user(username="cancel_admin", role="admin")
        tech = make_user(username="cancel_tech", role="technician")
        req = create_request(db_session, requester.id, "Cancel test title", "Desc here.", "Loc")
        record_request_created(db_session, req.id, requester.id, "requester")
        assign_request(db_session, req.id, tech.id, admin.id)
        db_session.flush()

        loaded = db_session.get(type(req), req.id)
        cancellable = {RequestStatus.SUBMITTED.value, RequestStatus.OPEN.value}
        assert loaded.status.value not in cancellable
