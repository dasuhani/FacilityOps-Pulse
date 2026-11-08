#!/usr/bin/env python3
"""
scripts/create_admin.py
------------------------
Safe, interactive CLI for creating the first (or any additional)
administrator account.

Usage:
    python scripts/create_admin.py

Design principles:
  - No default passwords.  Every value is entered interactively.
  - Passwords are read with getpass (never echoed to the terminal).
  - All validation rules are enforced before touching the database.
  - The script is idempotent: running it twice with the same username
    produces a clear duplicate-username error rather than silent data
    corruption.
  - The script can also be used to create additional admins or reset
    a locked-out admin's password (--reset-password flag).

Exit codes:
    0  success
    1  validation or DB error
    2  user aborted (Ctrl-C)
"""

import argparse
import getpass
import sys
from pathlib import Path

# Ensure the project root is on sys.path so imports work when the script
# is called from any working directory.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_banner() -> None:
    print("\n" + "=" * 60)
    print("  FacilityOps Pulse — Administrator Account Setup")
    print("=" * 60 + "\n")


def _prompt(label: str, required: bool = True, default: str = "") -> str:
    """Prompt for plain-text input, optionally with a default."""
    while True:
        suffix = f" [{default}]" if default else (" (required)" if required else " (optional)")
        value = input(f"  {label}{suffix}: ").strip()
        if not value and default:
            return default
        if not value and required:
            print(f"    ✗ '{label}' is required.")
            continue
        return value


def _prompt_password(label: str) -> str:
    """Prompt for a password (hidden input) with strength check."""
    from core.security import validate_password_strength
    while True:
        pw = getpass.getpass(f"  {label}: ")
        errors = validate_password_strength(pw)
        if errors:
            print("    ✗ Password does not meet requirements:")
            for e in errors:
                print(f"      - {e}")
            continue
        confirm = getpass.getpass(f"  Confirm {label}: ")
        if pw != confirm:
            print("    ✗ Passwords do not match. Try again.")
            continue
        return pw


def _confirm(message: str) -> bool:
    """Ask a yes/no question. Returns True for yes."""
    answer = input(f"\n  {message} [y/N]: ").strip().lower()
    return answer in ("y", "yes")


# ---------------------------------------------------------------------------
# Create admin
# ---------------------------------------------------------------------------

def create_admin() -> int:
    """
    Interactively collect admin details, validate, and persist.
    Returns 0 on success, 1 on error.
    """
    from database.connection import check_db_connection, create_tables_only
    from database.crud.user_crud import create_user, get_user_by_username
    from database.crud.audit_crud import log_user_created
    from database.connection import get_db
    from database.models.user import UserRole

    # 1. Verify database connectivity
    print("  Checking database connection…", end=" ", flush=True)
    ok, msg = check_db_connection()
    if not ok:
        print(f"FAILED\n\n  ✗ {msg}")
        print("\n  Fix your .env DB_* settings and try again.")
        return 1
    print("OK")

    # 2. Ensure tables exist (safe no-op if already created)
    print("  Ensuring schema is up to date…", end=" ", flush=True)
    try:
        create_tables_only()
        print("OK")
    except Exception as exc:
        print(f"FAILED\n\n  ✗ {exc}")
        return 1

    # 3. Collect details
    print()
    print("  Enter details for the new administrator account.")
    print("  (Press Ctrl-C at any time to abort.)\n")

    username = _prompt("Username")
    full_name = _prompt("Full Name")
    email = _prompt("Email Address")
    department = _prompt("Department", required=False)

    print()
    password = _prompt_password("Password")

    # 4. Preview and confirm
    print("\n  " + "-" * 54)
    print("  Account to be created:")
    print(f"    Username   : {username}")
    print(f"    Full Name  : {full_name}")
    print(f"    Email      : {email}")
    print(f"    Department : {department or '(not set)'}")
    print(f"    Role       : admin")
    print("  " + "-" * 54)

    if not _confirm("Create this administrator account?"):
        print("\n  Aborted. No changes were made.")
        return 0

    # 5. Persist
    try:
        with get_db() as session:
            # Check for username collision before hitting the DB constraint
            existing = get_user_by_username(session, username)
            if existing:
                print(
                    f"\n  ✗ A user with username '{username}' already exists "
                    f"(id={existing.id}, role={existing.role.value})."
                )
                return 1

            user = create_user(
                session=session,
                username=username,
                email=email,
                full_name=full_name,
                plain_password=password,
                role=UserRole.ADMIN,
                department=department or None,
            )
            # Audit: system-initiated creation (actor = new user themselves)
            log_user_created(
                session,
                actor_id=user.id,
                new_user_id=user.id,
                role=UserRole.ADMIN.value,
            )
            uid = user.id

        print(f"\n  ✓ Administrator account created successfully (id={uid}).")
        print(f"  You can now log in at http://localhost:8501 with username '{username}'.\n")
        return 0

    except ValueError as exc:
        print(f"\n  ✗ Validation error: {exc}")
        return 1
    except Exception as exc:
        print(f"\n  ✗ Unexpected error: {exc}")
        return 1


# ---------------------------------------------------------------------------
# Reset existing admin password
# ---------------------------------------------------------------------------

def reset_admin_password() -> int:
    """
    Interactively reset the password for an existing admin account.
    Returns 0 on success, 1 on error.
    """
    from database.connection import check_db_connection, get_db
    from database.crud.user_crud import get_user_by_username
    from database.crud.audit_crud import log_password_reset
    from core.security import hash_password
    from database.models.user import UserRole

    print("  Checking database connection…", end=" ", flush=True)
    ok, msg = check_db_connection()
    if not ok:
        print(f"FAILED\n\n  ✗ {msg}")
        return 1
    print("OK\n")

    username = _prompt("Username of admin to reset")
    new_password = _prompt_password("New Password")

    try:
        with get_db() as session:
            user = get_user_by_username(session, username)
            if not user:
                print(f"\n  ✗ No user found with username '{username}'.")
                return 1
            if user.role != UserRole.ADMIN:
                print(
                    f"\n  ✗ User '{username}' has role '{user.role.value}', not admin. "
                    "Use the application UI to reset non-admin passwords."
                )
                return 1

            if not _confirm(
                f"Reset password for admin '{username}' (id={user.id})?"
            ):
                print("\n  Aborted. No changes were made.")
                return 0

            user.password_hash = hash_password(new_password)
            log_password_reset(session, actor_id=user.id, target_user_id=user.id)

        print(f"\n  ✓ Password reset for admin '{username}'.\n")
        return 0

    except Exception as exc:
        print(f"\n  ✗ Error: {exc}")
        return 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="FacilityOps Pulse — Administrator account management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/create_admin.py              # create a new admin\n"
            "  python scripts/create_admin.py --reset      # reset an admin password\n"
        ),
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset the password for an existing administrator account.",
    )
    args = parser.parse_args()

    _print_banner()

    try:
        if args.reset:
            print("  Mode: Reset administrator password\n")
            rc = reset_admin_password()
        else:
            print("  Mode: Create new administrator account\n")
            rc = create_admin()
    except KeyboardInterrupt:
        print("\n\n  Interrupted by user. No changes were made.")
        rc = 2

    sys.exit(rc)


if __name__ == "__main__":
    main()
