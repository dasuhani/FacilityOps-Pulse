"""
tests/test_users.py
--------------------
Tests for:
  - User CRUD operations (create, read, update, deactivate)
  - Duplicate username / email rejection
  - Profile updates
  - Admin password reset
  - Technician skill CRUD
  - AuditLog writes for user operations
  - User.to_dict() safety (no password_hash exposure)
"""

import pytest
from sqlalchemy import select

from database.models.user import User, UserRole
from database.crud.user_crud import (
    create_user,
    get_user_by_id,
    get_user_by_username,
    get_user_by_email,
    get_all_users,
    get_technicians,
    update_user_profile,
    set_user_active,
    admin_reset_password,
    count_users_by_role,
)
from database.crud.skill_crud import (
    add_skill,
    add_skills_bulk,
    get_skills_for_technician,
    get_skill_categories_for_technician,
    remove_skill,
    skill_exists,
)
from database.crud.audit_crud import (
    get_audit_for_entity,
    log_user_created,
    log_user_deactivated,
)
from database.models.technician_skill import SkillCategory
from core.security import hash_password, verify_password


# ---------------------------------------------------------------------------
# User creation
# ---------------------------------------------------------------------------

class TestCreateUser:
    def test_create_requester(self, db_session):
        user = create_user(
            db_session,
            username="alice",
            email="alice@example.com",
            full_name="Alice Smith",
            plain_password="Alice@2024",
            role=UserRole.REQUESTER,
        )
        assert user.id is not None
        assert user.username == "alice"
        assert user.role == UserRole.REQUESTER
        assert user.is_active is True

    def test_create_technician(self, db_session):
        user = create_user(
            db_session,
            username="bob_tech",
            email="bob@example.com",
            full_name="Bob Technician",
            plain_password="Bob@Tech99",
            role=UserRole.TECHNICIAN,
        )
        assert user.role == UserRole.TECHNICIAN

    def test_create_admin(self, db_session):
        user = create_user(
            db_session,
            username="sysadmin",
            email="admin@example.com",
            full_name="System Admin",
            plain_password="Admin@Secure1",
            role=UserRole.ADMIN,
        )
        assert user.role == UserRole.ADMIN

    def test_duplicate_username_raises(self, db_session, make_user):
        make_user(username="duplicate")
        with pytest.raises(ValueError, match="already taken"):
            create_user(
                db_session,
                username="duplicate",
                email="other@example.com",
                full_name="Other User",
                plain_password="Other@1234",
            )

    def test_duplicate_email_raises(self, db_session, make_user):
        make_user(username="user1", email="shared@example.com")
        with pytest.raises(ValueError, match="already registered"):
            create_user(
                db_session,
                username="user2",
                email="shared@example.com",
                full_name="User Two",
                plain_password="User2@1234",
            )

    def test_username_is_lowercased(self, db_session):
        user = create_user(
            db_session,
            username="MixedCase",
            email="mixed@example.com",
            full_name="Mixed Case",
            plain_password="Mixed@Case1",
        )
        assert user.username == "mixedcase"

    def test_email_is_lowercased(self, db_session):
        user = create_user(
            db_session,
            username="emailtest",
            email="EMAIL@EXAMPLE.COM",
            full_name="Email Test",
            plain_password="Email@Test1",
        )
        assert user.email == "email@example.com"

    def test_password_is_not_stored_in_plaintext(self, db_session):
        user = create_user(
            db_session,
            username="pwcheck",
            email="pwcheck@example.com",
            full_name="Pw Check",
            plain_password="Pw@Check99",
        )
        assert user.password_hash != "Pw@Check99"
        assert user.password_hash.startswith("$2b$")

    def test_to_dict_excludes_password_hash(self, db_session):
        user = create_user(
            db_session,
            username="safedump",
            email="safedump@example.com",
            full_name="Safe Dump",
            plain_password="Safe@Dump1",
        )
        d = user.to_dict()
        assert "password_hash" not in d
        assert d["username"] == "safedump"
        assert d["role"] == "requester"


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

class TestReadUser:
    def test_get_by_id(self, db_session, make_user):
        user = make_user(username="getbyid")
        found = get_user_by_id(db_session, user.id)
        assert found is not None
        assert found.id == user.id

    def test_get_by_id_missing_returns_none(self, db_session):
        assert get_user_by_id(db_session, 99999) is None

    def test_get_by_username(self, db_session, make_user):
        make_user(username="findme")
        found = get_user_by_username(db_session, "findme")
        assert found is not None
        assert found.username == "findme"

    def test_get_by_username_case_insensitive(self, db_session, make_user):
        make_user(username="casetest")
        found = get_user_by_username(db_session, "CASETEST")
        assert found is not None

    def test_get_by_username_missing_returns_none(self, db_session):
        assert get_user_by_username(db_session, "nobody") is None

    def test_get_by_email(self, db_session, make_user):
        make_user(username="emailfind", email="emailfind@x.com")
        found = get_user_by_email(db_session, "emailfind@x.com")
        assert found is not None

    def test_get_all_users_active_only(self, db_session, make_user):
        make_user(username="active1", is_active=True)
        make_user(username="inactive1", is_active=False)
        users = get_all_users(db_session, active_only=True)
        usernames = [u.username for u in users]
        assert "active1" in usernames
        assert "inactive1" not in usernames

    def test_get_all_users_includes_inactive(self, db_session, make_user):
        make_user(username="active2", is_active=True)
        make_user(username="inactive2", is_active=False)
        users = get_all_users(db_session, active_only=False)
        usernames = [u.username for u in users]
        assert "inactive2" in usernames

    def test_get_technicians_filters_by_role(self, db_session, make_user):
        make_user(username="tech_r", role="technician")
        make_user(username="req_r", role="requester")
        techs = get_technicians(db_session)
        roles = {t.role for t in techs}
        assert roles == {UserRole.TECHNICIAN}

    def test_count_users_by_role(self, db_session, make_user):
        make_user(username="cr1", role="requester")
        make_user(username="cr2", role="requester")
        make_user(username="ct1", role="technician")
        counts = count_users_by_role(db_session)
        assert counts.get("requester", 0) >= 2
        assert counts.get("technician", 0) >= 1


# ---------------------------------------------------------------------------
# Update operations
# ---------------------------------------------------------------------------

class TestUpdateUser:
    def test_update_full_name(self, db_session, make_user):
        user = make_user(username="upd_name")
        updated = update_user_profile(db_session, user.id, full_name="New Name")
        assert updated.full_name == "New Name"

    def test_update_email(self, db_session, make_user):
        user = make_user(username="upd_email", email="old@x.com")
        updated = update_user_profile(db_session, user.id, email="new@x.com")
        assert updated.email == "new@x.com"

    def test_update_email_collision_raises(self, db_session, make_user):
        make_user(username="taken_email", email="taken@x.com")
        user2 = make_user(username="other_user", email="other@x.com")
        with pytest.raises(ValueError, match="already in use"):
            update_user_profile(db_session, user2.id, email="taken@x.com")

    def test_update_nonexistent_user_raises(self, db_session):
        with pytest.raises(ValueError, match="not found"):
            update_user_profile(db_session, 99999, full_name="Ghost")

    def test_deactivate_user(self, db_session, make_user):
        user = make_user(username="deact_me")
        result = set_user_active(db_session, user.id, False)
        assert result.is_active is False

    def test_reactivate_user(self, db_session, make_user):
        user = make_user(username="react_me", is_active=False)
        result = set_user_active(db_session, user.id, True)
        assert result.is_active is True

    def test_admin_reset_password(self, db_session, make_user):
        user = make_user(username="resetpw", password="OldPass@1")
        admin_reset_password(db_session, user.id, "NewPass@2")
        refreshed = get_user_by_id(db_session, user.id)
        assert verify_password("NewPass@2", refreshed.password_hash)
        assert not verify_password("OldPass@1", refreshed.password_hash)


# ---------------------------------------------------------------------------
# TechnicianSkill CRUD
# ---------------------------------------------------------------------------

class TestTechnicianSkills:
    def test_add_skill(self, db_session, make_user):
        tech = make_user(username="skilled_tech", role="technician")
        skill = add_skill(db_session, tech.id, SkillCategory.PLUMBING)
        assert skill.id is not None
        assert skill.skill_category == SkillCategory.PLUMBING

    def test_add_duplicate_skill_raises(self, db_session, make_user):
        tech = make_user(username="dup_skill_tech", role="technician")
        add_skill(db_session, tech.id, SkillCategory.ELECTRICAL)
        with pytest.raises(ValueError, match="already has skill"):
            add_skill(db_session, tech.id, SkillCategory.ELECTRICAL)

    def test_skill_exists(self, db_session, make_user):
        tech = make_user(username="skill_exist_tech", role="technician")
        assert not skill_exists(db_session, tech.id, SkillCategory.HVAC)
        add_skill(db_session, tech.id, SkillCategory.HVAC)
        assert skill_exists(db_session, tech.id, SkillCategory.HVAC)

    def test_get_skills_for_technician(self, db_session, make_user):
        tech = make_user(username="multi_skill_tech", role="technician")
        add_skills_bulk(
            db_session, tech.id,
            [SkillCategory.NETWORKING, SkillCategory.HARDWARE, SkillCategory.SOFTWARE]
        )
        skills = get_skills_for_technician(db_session, tech.id)
        cats = {s.skill_category for s in skills}
        assert SkillCategory.NETWORKING in cats
        assert SkillCategory.HARDWARE in cats

    def test_get_skill_categories(self, db_session, make_user):
        tech = make_user(username="cat_skill_tech", role="technician")
        add_skill(db_session, tech.id, SkillCategory.PAINTING)
        cats = get_skill_categories_for_technician(db_session, tech.id)
        assert "painting" in cats

    def test_remove_skill(self, db_session, make_user):
        tech = make_user(username="rem_skill_tech", role="technician")
        add_skill(db_session, tech.id, SkillCategory.CARPENTRY)
        remove_skill(db_session, tech.id, SkillCategory.CARPENTRY)
        assert not skill_exists(db_session, tech.id, SkillCategory.CARPENTRY)

    def test_bulk_add_skips_duplicates(self, db_session, make_user):
        tech = make_user(username="bulk_skill_tech", role="technician")
        add_skill(db_session, tech.id, SkillCategory.SERVERS)
        # Servers is already there — bulk add should not raise, just skip it
        created = add_skills_bulk(
            db_session, tech.id,
            [SkillCategory.SERVERS, SkillCategory.AV_EQUIPMENT]
        )
        # Only AV_EQUIPMENT should be newly created
        assert len(created) == 1
        assert created[0].skill_category == SkillCategory.AV_EQUIPMENT


# ---------------------------------------------------------------------------
# AuditLog for user operations
# ---------------------------------------------------------------------------

class TestUserAuditLog:
    def test_audit_entry_written_on_user_creation(self, db_session, make_user):
        user = make_user(username="audit_created")
        log_user_created(db_session, actor_id=user.id, new_user_id=user.id, role="requester")

        entries = get_audit_for_entity(db_session, "user", user.id)
        actions = [e.action for e in entries]
        assert "user.created" in actions

    def test_audit_entry_written_on_deactivation(self, db_session, make_user):
        user = make_user(username="audit_deact")
        log_user_deactivated(db_session, actor_id=user.id, target_user_id=user.id)

        entries = get_audit_for_entity(db_session, "user", user.id)
        actions = [e.action for e in entries]
        assert "user.deactivated" in actions

    def test_audit_outcome_defaults_to_success(self, db_session, make_user):
        user = make_user(username="audit_outcome")
        log_user_created(db_session, actor_id=user.id, new_user_id=user.id, role="requester")
        entries = get_audit_for_entity(db_session, "user", user.id)
        assert all(e.outcome == "success" for e in entries)
