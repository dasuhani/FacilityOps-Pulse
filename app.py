"""
app.py
------
FacilityOps Pulse — Streamlit application entry point.

This file is the ONLY file Streamlit runs directly:
    streamlit run app.py

Responsibilities:
  1. Configure the Streamlit page (must be first st call).
  2. Set up logging.
  3. Initialise the database (create tables + seed admin on first run).
  4. Render the page header and sidebar navigation.
  5. Route to the correct page module based on authentication state and
     the current_page key in session state.

No business logic or UI rendering lives here — everything is delegated
to app/pages/* and app/components/*.
"""

import logging
import sys

import streamlit as st

# ---------------------------------------------------------------------------
# 1. Page configuration — must be the very first Streamlit call
# ---------------------------------------------------------------------------
from app.components.layout import configure_page
configure_page()

# ---------------------------------------------------------------------------
# 2. Logging setup
# ---------------------------------------------------------------------------
from core.logger import setup_logging
from core.config import settings

setup_logging(log_level=settings.LOG_LEVEL, log_file=settings.LOG_FILE)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 3. Database initialisation (safe to run every startup — idempotent)
# ---------------------------------------------------------------------------
from database.connection import init_db, check_db_connection

@st.cache_resource(show_spinner=False)
def _initialise_database():
    """
    Run once per Streamlit server process via st.cache_resource.
    Returns (success: bool, message: str).
    """
    ok, msg = check_db_connection()
    if not ok:
        return False, msg
    try:
        init_db()
        return True, "OK"
    except Exception as exc:
        logger.critical("Database initialisation failed: %s", exc)
        return False, str(exc)

db_ok, db_msg = _initialise_database()

# ---------------------------------------------------------------------------
# 4. Imports for rendering (after DB init so models are registered)
# ---------------------------------------------------------------------------
from app.components.layout import render_header, render_sidebar
from core.security import is_authenticated, get_current_role

# Page modules
from app.pages import auth as auth_page
from app.pages import requester as requester_page
from app.pages import technician as technician_page
from app.pages import admin as admin_page

# ---------------------------------------------------------------------------
# 5. Database connectivity guard
# ---------------------------------------------------------------------------
if not db_ok:
    st.error(
        "## 🔴 Database Connection Failed\n\n"
        f"**Error:** {db_msg}\n\n"
        "**Steps to fix:**\n"
        "1. Make sure PostgreSQL is running.\n"
        "2. Check `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` in your `.env` file.\n"
        "3. Verify the database and user exist:\n"
        "   ```sql\n"
        "   CREATE DATABASE facilityops_pulse;\n"
        "   CREATE USER facilityops_user WITH PASSWORD 'your_password';\n"
        "   GRANT ALL PRIVILEGES ON DATABASE facilityops_pulse TO facilityops_user;\n"
        "   ```\n"
        "4. Restart the application after fixing the configuration."
    )
    st.stop()

# ---------------------------------------------------------------------------
# 6. Render layout shell
# ---------------------------------------------------------------------------
render_header()

# If not authenticated, show auth page (no sidebar)
if not is_authenticated():
    auth_page.render()
    st.stop()

# Authenticated — render sidebar and get current page
current_page = render_sidebar()
role = get_current_role()

# ---------------------------------------------------------------------------
# 7. Route to the correct page module
# ---------------------------------------------------------------------------

# --- Requester routes ---
if role == "requester":
    if current_page == "requester_dashboard":
        requester_page.render_dashboard()
    elif current_page == "submit_request":
        requester_page.render_submit_request()
    elif current_page == "profile":
        requester_page.render_profile()
    else:
        requester_page.render_dashboard()

# --- Technician routes ---
elif role == "technician":
    if current_page == "technician_queue":
        technician_page.render_queue()
    elif current_page == "profile":
        technician_page.render_profile()
    else:
        technician_page.render_queue()

# --- Admin routes ---
elif role == "admin":
    if current_page == "admin_dashboard":
        admin_page.render_dashboard()
    elif current_page == "admin_requests":
        admin_page.render_requests()
    elif current_page == "admin_users":
        admin_page.render_users()
    elif current_page == "admin_locations":
        admin_page.render_locations()
    elif current_page == "admin_analytics":
        admin_page.render_analytics()
    elif current_page == "ai_reports":
        admin_page.render_ai_reports()
    elif current_page == "profile":
        admin_page.render_profile()
    else:
        admin_page.render_dashboard()

# --- Unknown role guard ---
else:
    st.error(
        f"Unknown role: `{role}`. "
        "Please contact an administrator to fix your account role."
    )
    logger.error("Unknown role '%s' for authenticated user — cannot route.", role)
