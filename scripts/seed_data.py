#!/usr/bin/env python3
"""
scripts/seed_data.py
---------------------
Seed the FacilityOps Pulse database with realistic demonstration data.

Produces:
  - 1 administrator
  - 3 technicians with different skills
  - 5 requesters
  - 6 facility locations
  - 28 service requests across all categories, priorities, and statuses
  - Some overdue requests (created far in the past)
  - Some recurring issues (same location, same category)
  - Resolved requests with status history, comments, and resolution notes

All records are labeled as DEMONSTRATION DATA. No real PII is used.
All passwords are set to "Demo@Pass1234" — change them after seeding.

Usage:
    python scripts/seed_data.py          # seed (idempotent — skips if data exists)
    python scripts/seed_data.py --force  # wipe and reseed

Exit codes:
    0  success
    1  database error
    2  interrupted
"""

import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data definitions
# ---------------------------------------------------------------------------

DEMO_PASSWORD = "Demo@Pass1234"

LOCATIONS = [
    {"building_name": "Main Office Tower", "floor": "1", "area": "Reception Lobby", "description": "Front desk and waiting area"},
    {"building_name": "Main Office Tower", "floor": "2", "area": "Open Plan Office", "description": "Second-floor open workspace"},
    {"building_name": "Main Office Tower", "floor": "3", "area": "Server Room", "description": "IT infrastructure room"},
    {"building_name": "Warehouse Building", "floor": "G", "area": "Loading Bay", "description": "Goods receiving and dispatch"},
    {"building_name": "Warehouse Building", "floor": "1", "area": "Staff Break Room", "description": "Kitchen and rest area"},
    {"building_name": "Annex Block", "floor": "2", "area": "Conference Room A", "description": "Meeting room with AV equipment"},
]

USERS = [
    # Admin
    {"username": "demo_admin", "full_name": "Demo Administrator", "email": "demo.admin@facilityops.demo",
     "role": "admin", "department": "Operations Management"},
    # Technicians
    {"username": "demo_tech_elec", "full_name": "Demo Tech (Electrical)", "email": "tech.elec@facilityops.demo",
     "role": "technician", "department": "Facilities"},
    {"username": "demo_tech_it", "full_name": "Demo Tech (IT)", "email": "tech.it@facilityops.demo",
     "role": "technician", "department": "IT Support"},
    {"username": "demo_tech_gen", "full_name": "Demo Tech (General)", "email": "tech.gen@facilityops.demo",
     "role": "technician", "department": "Facilities"},
    # Requesters
    {"username": "demo_req1", "full_name": "Demo Requester One", "email": "req1@facilityops.demo",
     "role": "requester", "department": "Finance"},
    {"username": "demo_req2", "full_name": "Demo Requester Two", "email": "req2@facilityops.demo",
     "role": "requester", "department": "Human Resources"},
    {"username": "demo_req3", "full_name": "Demo Requester Three", "email": "req3@facilityops.demo",
     "role": "requester", "department": "Sales"},
    {"username": "demo_req4", "full_name": "Demo Requester Four", "email": "req4@facilityops.demo",
     "role": "requester", "department": "Marketing"},
    {"username": "demo_req5", "full_name": "Demo Requester Five", "email": "req5@facilityops.demo",
     "role": "requester", "department": "Operations"},
]

TECH_SKILLS = {
    "demo_tech_elec": ["electrical", "hvac", "general_maintenance"],
    "demo_tech_it": ["networking", "hardware", "software"],
    "demo_tech_gen": ["plumbing", "cleaning", "general_maintenance"],
}

# 28 requests covering all categories, priorities, and statuses
# Each tuple: (title, description, location_idx, category, priority, status, days_ago_created,
#              requester_idx, tech_idx_or_None, overdue_bool, resolved_days_ago_or_None)
REQUESTS = [
    # --- Electrical ---
    ("Flickering lights in open plan office",
     "The fluorescent lights on the second floor have been flickering for three days. "
     "It is causing eye strain for the staff working in that area.",
     1, "electrical", "medium", "submitted", 2, 4, None, False, None),
    ("Exposed wiring near reception desk",
     "There is exposed electrical wiring visible behind the reception desk. "
     "This could be a safety hazard for visitors and staff.",
     0, "electrical", "critical", "assigned", 1, 0, 0, True, None),
    ("Power outlet not working in conference room",
     "The power outlet next to the projector in Conference Room A is not working. "
     "We need it for presentations.",
     5, "electrical", "low", "resolved", 15, 5, 0, False, 13),

    # --- Plumbing ---
    ("Leaking pipe under sink in break room",
     "Water is dripping from the pipe under the kitchen sink in the staff break room. "
     "A bucket has been placed to catch the water but it needs fixing.",
     4, "plumbing", "high", "in_progress", 3, 1, 2, False, None),
    ("Toilet not flushing in second-floor restroom",
     "The toilet in the men's restroom on the second floor won't flush. "
     "The handle seems to be broken.",
     1, "plumbing", "medium", "submitted", 1, 2, None, False, None),
    ("Water leak from ceiling in loading bay",
     "Water is leaking from the ceiling in the loading bay area after heavy rain. "
     "The floor is wet and could be a slip hazard.",
     3, "plumbing", "high", "assigned", 2, 3, 2, True, None),
    # Recurring plumbing issue at same location
    ("Leaking pipe under sink in break room (again)",
     "The pipe under the kitchen sink in the break room is leaking again after the previous fix. "
     "The water flow seems worse this time.",
     4, "plumbing", "high", "submitted", 1, 1, None, False, None),

    # --- HVAC ---
    ("Air conditioning not cooling in server room",
     "The AC unit in the server room is running but not producing cold air. "
     "Temperature is rising and we are concerned about the servers overheating.",
     2, "hvac", "critical", "in_progress", 1, 0, 0, True, None),
    ("Heating not working in annex conference room",
     "The heating system in Conference Room A (Annex Block) is not working. "
     "The room is too cold for meetings during winter.",
     5, "hvac", "medium", "resolved", 20, 5, 0, False, 18),
    ("Thermostat broken in open plan office",
     "The thermostat on the second floor shows 30°C but the actual temperature feels normal. "
     "The reading is unreliable and needs calibration.",
     1, "hvac", "low", "closed", 25, 4, 0, False, 22),

    # --- Cleaning ---
    ("Restroom needs deep cleaning",
     "The second-floor restroom needs a deep clean. The floors are sticky and "
     "the soap dispensers are empty.",
     1, "cleaning", "medium", "submitted", 1, 2, None, False, None),
    ("Spill in loading bay needs cleanup",
     "There is a large liquid spill in the loading bay that needs to be cleaned up "
     "before it becomes a slip hazard.",
     3, "cleaning", "high", "assigned", 0, 3, 2, False, None),
    ("Trash bins in conference room overflowing",
     "The trash bins in Conference Room A have not been emptied in a week. "
     "They are overflowing and attracting pests.",
     5, "cleaning", "low", "resolved", 10, 5, 2, False, 8),
    # Recurring cleaning issue
    ("Restroom needs deep cleaning (follow-up)",
     "The second-floor restroom requires another deep clean — the previous cleaning "
     "did not resolve the sticky floor issue completely.",
     1, "cleaning", "medium", "submitted", 0, 2, None, False, None),

    # --- Safety ---
    ("Fire extinguisher inspection overdue",
     "The fire extinguisher in the server room has an inspection sticker that expired "
     "two months ago. This needs immediate attention for compliance.",
     2, "safety", "critical", "submitted", 1, 0, None, False, None),
    ("Wet floor sign missing in reception area",
     "The floor was mopped in the reception lobby but no wet floor sign was placed. "
     "This is a slip hazard for visitors.",
     0, "safety", "high", "resolved", 8, 4, 0, False, 6),
    ("Emergency exit sign not illuminated",
     "The emergency exit sign in the loading bay is not illuminated. "
     "This is a safety compliance issue.",
     3, "safety", "high", "assigned", 3, 3, 0, True, None),

    # --- Equipment Maintenance ---
    ("Elevator making unusual noise",
     "The elevator in Main Office Tower is making a grinding noise when moving "
     "between floors. It may need maintenance or lubrication.",
     0, "equipment_maintenance", "medium", "in_progress", 5, 1, 2, False, None),
    ("Office chair broken in open plan",
     "One of the office chairs in the open plan area has a broken height adjustment. "
     "It cannot be raised or lowered.",
     1, "equipment_maintenance", "low", "submitted", 2, 4, None, False, None),
    ("Door lock on conference room sticking",
     "The door lock on Conference Room A is sticking and difficult to open. "
     "The key has to be jiggled to get it to turn.",
     5, "equipment_maintenance", "low", "closed", 30, 5, 2, False, 27),

    # --- IT Support ---
    ("Email server not responding",
     "The email server has been unresponsive for the past hour. "
     "Multiple users in the Finance and HR departments cannot send or receive emails.",
     2, "it_support", "high", "assigned", 0, 0, 1, True, None),
    ("Printer driver installation needed",
     "The new printer in the open plan office needs driver installation on "
     "three workstations in the Sales department.",
     1, "it_support", "low", "resolved", 12, 2, 1, False, 10),
    ("Software license expired for design tool",
     "The design software license used by the Marketing team has expired. "
     "Users cannot open their project files.",
     1, "it_support", "medium", "submitted", 1, 3, None, False, None),

    # --- Network & Wi-Fi ---
    ("Wi-Fi not working in conference room",
     "The Wi-Fi signal in Conference Room A is very weak or non-existent. "
     "Meeting attendees cannot connect to present or access online resources.",
     5, "network_wifi", "medium", "in_progress", 2, 5, 1, False, None),
    ("Network switch in server room not responding",
     "The primary network switch in the server room is not responding to pings. "
     "All network connectivity in the building is affected.",
     2, "network_wifi", "critical", "assigned", 0, 0, 1, True, None),
    ("Slow internet speed in warehouse building",
     "The internet connection in the Warehouse Building is extremely slow. "
     "Staff cannot access cloud applications efficiently.",
     3, "network_wifi", "low", "submitted", 3, 3, None, False, None),

    # --- Computer & Display ---
    ("Monitor flickering in open plan office",
     "One of the monitors in the open plan office is flickering and showing "
     "horizontal lines. It may need to be replaced.",
     1, "computer_display", "low", "submitted", 1, 4, None, False, None),
    ("Projector in conference room not displaying",
     "The projector in Conference Room A is turning on but not displaying "
     "any input. HDMI and VGA cables have been tested.",
     5, "computer_display", "medium", "resolved", 7, 5, 1, False, 5),
]

COMMENTS = [
    # (request_index, user_index, comment, days_ago)
    (2, 0, "Inspected the power outlet. Found a tripped breaker. Reset it and tested — working now.", 13),
    (2, 5, "Thanks for fixing this quickly. The outlet is working fine now.", 12),
    (4, 2, "Started investigating the leak. The U-bend pipe has a crack. Ordering replacement.", 2),
    (7, 0, "Checked the AC unit. The refrigerant level is low. Recharging the system now.", 0),
    (8, 0, "Replaced the heating element and tested. The room reaches target temperature now.", 18),
    (12, 2, "Cleaned the break room. Trash bins emptied and floors mopped.", 8),
    (15, 0, "Placed a wet floor sign. Will order a replacement sign for permanent placement.", 6),
]


# ---------------------------------------------------------------------------
# Seed logic
# ---------------------------------------------------------------------------

def seed(force: bool = False) -> int:
    """Run the seed. Returns 0 on success, 1 on error."""
    from database.connection import get_db, check_db_connection, create_tables_only
    from database.models.user import User, UserRole
    from database.models.request import ServiceRequest, RequestCategory, RequestPriority, RequestStatus
    from database.models.technician_skill import TechnicianSkill, SkillCategory
    from database.models.location import Location
    from database.crud.user_crud import create_user, get_user_by_username
    from database.crud.skill_crud import add_skill
    from database.crud.request_crud import create_request, update_request_status, update_resolution_notes
    from database.crud.location_crud import create_location
    from database.crud.assignment_crud import assign_request
    from database.crud.history_crud import record_request_created
    from database.crud.comment_crud import add_comment
    from core.security import hash_password
    from sqlalchemy import select, func

    # Check DB
    ok, msg = check_db_connection()
    if not ok:
        print(f"✗ Database connection failed: {msg}")
        return 1

    print("✓ Database connected.")
    create_tables_only()
    print("✓ Schema ready.")

    with get_db() as session:
        # Check if demo data already exists
        existing = session.scalar(
            select(func.count(User.id)).where(User.username.like("demo_%"))
        )
        if existing and not force:
            print(f"ℹ Demo data already exists ({existing} demo users). Use --force to reseed.")
            return 0

        if force:
            print("⚠ Wiping existing demo data…")
            # Delete in dependency order
            from database.models.request_comment import RequestComment
            from database.models.request_history import RequestHistory
            from database.models.status_history import StatusHistory
            from database.models.assignment import Assignment
            from database.models.audit_log import AuditLog
            session.query(RequestComment).delete()
            session.query(RequestHistory).delete()
            session.query(StatusHistory).delete()
            session.query(Assignment).delete()
            session.query(ServiceRequest).delete()
            session.query(TechnicianSkill).delete()
            session.query(Location).delete()
            session.query(AuditLog).delete()
            session.query(User).filter(User.username.like("demo_%")).delete()
            session.flush()
            print("✓ Demo data wiped.")

        # --- Create locations ---
        print("Seeding locations…")
        loc_objs = []
        for loc_data in LOCATIONS:
            loc = create_location(
                session,
                building_name=loc_data["building_name"],
                floor=loc_data["floor"],
                area=loc_data["area"],
                description=loc_data["description"],
            )
            loc_objs.append(loc)
        print(f"  ✓ {len(loc_objs)} locations created.")

        # --- Create users ---
        print("Seeding users…")
        user_objs = {}
        for user_data in USERS:
            try:
                user = create_user(
                    session,
                    username=user_data["username"],
                    email=user_data["email"],
                    full_name=user_data["full_name"],
                    plain_password=DEMO_PASSWORD,
                    role=UserRole(user_data["role"]),
                    department=user_data["department"],
                )
                user_objs[user_data["username"]] = user
            except ValueError:
                # Already exists
                user_objs[user_data["username"]] = get_user_by_username(session, user_data["username"])
        print(f"  ✓ {len(user_objs)} users created (1 admin, 3 technicians, 5 requesters).")

        # --- Assign technician skills ---
        print("Seeding technician skills…")
        for tech_username, skills in TECH_SKILLS.items():
            tech = user_objs.get(tech_username)
            if not tech:
                continue
            for skill_val in skills:
                try:
                    add_skill(session, tech.id, SkillCategory(skill_val))
                except ValueError:
                    pass  # Already has it
        print("  ✓ Skills assigned to technicians.")

        # --- Create requests ---
        print("Seeding service requests…")
        now = datetime.now(timezone.utc)
        req_objs = []

        for i, req_data in enumerate(REQUESTS):
            (title, description, loc_idx, category, priority, status,
             days_ago_created, requester_idx, tech_idx, is_overdue, resolved_days_ago) = req_data

            requester = list(user_objs.values())[requester_idx + 3]  # Skip admin + 3 techs
            loc = loc_objs[loc_idx]

            # Create the request
            req = create_request(
                session,
                requester_id=requester.id,
                title=title,
                description=description,
                location=loc.display_name(),
                category=RequestCategory(category),
                priority=RequestPriority(priority),
                building=loc.building_name,
                floor_or_room=loc.floor,
            )
            req.location_id = loc.id

            # Set created_at to simulate age
            req.created_at = now - timedelta(days=days_ago_created)

            # Record creation history
            record_request_created(session, req.id, requester.id, "requester")

            # Assign technician if specified
            if tech_idx is not None:
                tech_list = [v for k, v in user_objs.items() if v.role == UserRole.TECHNICIAN]
                tech = tech_list[tech_idx]
                assign_request(
                    session,
                    request_id=req.id,
                    technician_id=tech.id,
                    assigned_by_id=user_objs["demo_admin"].id,
                    assignment_notes="Demo assignment for testing.",
                )

            # Set final status
            if status == "resolved" and resolved_days_ago is not None:
                update_request_status(
                    session, req.id, RequestStatus.RESOLVED,
                    user_objs["demo_admin"].id, "admin",
                    note="Issue resolved during demo.",
                )
                req.resolved_at = now - timedelta(days=resolved_days_ago)
                update_resolution_notes(session, req.id,
                    f"Resolution completed. Verified by demo technician. "
                    f"[DEMO DATA] Issue addressed on {req.resolved_at.strftime('%Y-%m-%d')}.")
            elif status == "closed" and resolved_days_ago is not None:
                update_request_status(
                    session, req.id, RequestStatus.RESOLVED,
                    user_objs["demo_admin"].id, "admin",
                    note="Resolved and verified.",
                )
                req.resolved_at = now - timedelta(days=resolved_days_ago + 2)
                update_resolution_notes(session, req.id,
                    f"Closed after confirmation. [DEMO DATA]")
                update_request_status(
                    session, req.id, RequestStatus.CLOSED,
                    user_objs["demo_admin"].id, "admin",
                    note="Closed by admin.",
                )
                req.closed_at = now - timedelta(days=resolved_days_ago)
            elif status != "submitted":
                # Already assigned (which may have set to "assigned"), just ensure correct status
                try:
                    update_request_status(
                        session, req.id, RequestStatus(status),
                        user_objs["demo_admin"].id, "admin",
                        note=f"Status set to {status} for demo.",
                    )
                except ValueError:
                    pass

            # Mark overdue by adjusting created_at further back if needed
            if is_overdue:
                from business.analytics_service import SLA_HOURS
                sla = SLA_HOURS.get(priority, 24)
                # Set created_at far enough back to breach SLA
                min_hours_needed = sla + 2
                min_days = max(days_ago_created, int(min_hours_needed / 24) + 1)
                req.created_at = now - timedelta(days=min_days)

            req_objs.append(req)
            session.flush()

        print(f"  ✓ {len(req_objs)} service requests created.")

        # --- Add comments ---
        print("Seeding comments…")
        for req_idx, user_idx, comment_text, days_ago in COMMENTS:
            if req_idx >= len(req_objs):
                continue
            req = req_objs[req_idx]
            user_list = list(user_objs.values())
            if user_idx >= len(user_list):
                continue
            commenter = user_list[user_idx]
            try:
                add_comment(session, req.id, commenter.id, f"{comment_text} [DEMO DATA]")
            except ValueError:
                pass
        print("  ✓ Comments added to resolved requests.")

    print("\n✅ Seed complete!")
    print(f"   - 1 admin: demo_admin / {DEMO_PASSWORD}")
    print(f"   - 3 technicians: demo_tech_elec, demo_tech_it, demo_tech_gen")
    print(f"   - 5 requesters: demo_req1 through demo_req5")
    print(f"   - 6 locations, {len(REQUESTS)} requests, comments on resolved items")
    print(f"   - All passwords: {DEMO_PASSWORD}")
    print(f"\n   ⚠ All records are labeled as DEMO DATA. Do not use in production.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed FacilityOps Pulse with demonstration data",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Wipe existing demo data and reseed.",
    )
    args = parser.parse_args()

    try:
        rc = seed(force=args.force)
    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        rc = 2
    sys.exit(rc)


if __name__ == "__main__":
    main()
