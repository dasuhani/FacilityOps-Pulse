"""
app/components/layout.py
-------------------------
Shared page layout helpers: Streamlit page config, header banner,
sidebar navigation, role badges, and notification toasts.

All page modules import from here to keep visual consistency.
"""

import streamlit as st
from core.security import get_current_user, logout_user, get_current_role
from core.config import settings

# ---------------------------------------------------------------------------
# Brand constants
# ---------------------------------------------------------------------------

APP_NAME = settings.APP_NAME
APP_TAGLINE = "Facility & IT Service Management"
APP_ICON = "🏢"

ROLE_COLOURS = {
    "admin": "#dc2626",        # red
    "technician": "#2563eb",   # blue
    "requester": "#16a34a",    # green
}

ROLE_ICONS = {
    "admin": "🛡️",
    "technician": "🔧",
    "requester": "👤",
}

STATUS_COLOURS = {
    "submitted": "#6366f1",    # Indigo
    "open": "#6b7280",         # Grey (legacy)
    "assigned": "#2563eb",     # Blue
    "in_progress": "#0891b2",  # Cyan
    "on_hold": "#d97706",      # Amber
    "resolved": "#16a34a",     # Green
    "closed": "#374151",       # Dark grey
    "cancelled": "#dc2626",   # Red
}

PRIORITY_COLOURS = {
    "low": "#16a34a",
    "medium": "#d97706",
    "high": "#ea580c",
    "critical": "#dc2626",
}

STATUS_EMOJI = {
    "submitted": "📥",
    "open": "📋",            # legacy
    "assigned": "👤",
    "in_progress": "🔧",
    "on_hold": "⏸️",
    "resolved": "✅",
    "closed": "🔒",
    "cancelled": "❌",
}

PRIORITY_EMOJI = {
    "low": "🟢",
    "medium": "🟡",
    "high": "🟠",
    "critical": "🔴",
}


# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

def configure_page(title: str = APP_NAME) -> None:
    """
    Call st.set_page_config. Must be the very first Streamlit call in app.py.
    Only call this once from app.py — not from individual page modules.
    """
    st.set_page_config(
        page_title=f"{title} | {APP_TAGLINE}",
        page_icon=APP_ICON,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_css()


def _inject_css() -> None:
    """Inject custom CSS for a polished, modern SaaS-style interface."""
    st.markdown(
        """
        <style>
        /* Metric cards — SaaS-style elevated cards */
        [data-testid="metric-container"] {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 10px;
            padding: 14px 18px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12);
            transition: border-color 0.2s;
        }
        [data-testid="metric-container"]:hover {
            border-color: rgba(99, 102, 241, 0.3);
        }
        [data-testid="metric-container"] > div > label {
            font-size: 0.82rem;
            color: #9ca3af;
            font-weight: 500;
        }
        [data-testid="metric-container"] > div > div {
            font-size: 1.6rem;
            font-weight: 700;
        }
        /* Status badge pill */
        .badge {
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.78rem;
            font-weight: 600;
            color: white;
        }
        /* Highlight SLA breach rows */
        .sla-breach {
            background-color: rgba(220, 38, 38, 0.1);
        }
        /* Info panel */
        .info-panel {
            background: rgba(37, 99, 235, 0.08);
            border-left: 4px solid #2563eb;
            padding: 12px 16px;
            border-radius: 4px;
            margin-bottom: 12px;
        }
        /* Empty state panel */
        .empty-state {
            text-align: center;
            padding: 40px 20px;
            color: #6b7280;
        }
        .empty-state-icon {
            font-size: 3rem;
            margin-bottom: 12px;
        }
        /* Filter bar */
        .filter-bar {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 10px;
            padding: 12px 16px;
            margin-bottom: 16px;
        }
        /* Section headers */
        .section-header {
            font-size: 1.05rem;
            font-weight: 600;
            color: #e5e7eb;
            margin-top: 8px;
            margin-bottom: 8px;
        }
        /* Make dividers subtler */
        hr { opacity: 0.2; }
        /* Plotly chart containers — tighter margins */
        .stPlotlyChart {
            margin-top: -8px;
        }
        /* Sidebar polish */
        [data-testid="stSidebar"] {
            border-right: 1px solid rgba(255,255,255,0.06);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Header / branding
# ---------------------------------------------------------------------------

def render_header() -> None:
    """Render the top app header with branding and logged-in user info."""
    user = get_current_user()
    col_logo, col_user = st.columns([3, 1])

    with col_logo:
        st.markdown(
            f"## {APP_ICON} {APP_NAME}",
            help=APP_TAGLINE,
        )

    if user:
        role = user.get("role", "")
        icon = ROLE_ICONS.get(role, "👤")
        colour = ROLE_COLOURS.get(role, "#6b7280")
        with col_user:
            st.markdown(
                f"<div style='text-align:right; padding-top:10px;'>"
                f"<span style='font-size:0.9rem; color:{colour}; font-weight:600;'>"
                f"{icon} {user.get('full_name', user.get('username', ''))}</span>"
                f"<br/><span style='font-size:0.75rem; color:#9ca3af;'>"
                f"{role.title()}</span></div>",
                unsafe_allow_html=True,
            )

    st.divider()


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------

def render_sidebar() -> str:
    """
    Render the sidebar with role-appropriate navigation links.
    Returns the currently selected page key (string).
    """
    user = get_current_user()

    with st.sidebar:
        st.markdown(f"### {APP_ICON} {APP_NAME}")
        st.caption(APP_TAGLINE)
        st.divider()

        if not user:
            # Not logged in — no nav needed
            return "auth"

        role = user.get("role", "requester")
        icon = ROLE_ICONS.get(role, "👤")
        colour = ROLE_COLOURS.get(role, "#6b7280")

        st.markdown(
            f"<div class='info-panel'>"
            f"{icon} <strong>{user.get('full_name', user.get('username'))}</strong>"
            f"<br/><span style='color:{colour}; font-size:0.8rem;'>"
            f"{role.upper()}</span></div>",
            unsafe_allow_html=True,
        )

        # Role-specific navigation
        if role == "requester":
            pages = {
                "📋 My Requests": "requester_dashboard",
                "➕ Submit Request": "submit_request",
                "👤 My Profile": "profile",
            }
        elif role == "technician":
            pages = {
                "🔧 My Work Queue": "technician_queue",
                "👤 My Profile": "profile",
            }
        else:  # admin
            pages = {
                "📊 Dashboard": "admin_dashboard",
                "📋 All Requests": "admin_requests",
                "👥 Manage Users": "admin_users",
                "📍 Locations": "admin_locations",
                "📈 Analytics": "admin_analytics",
                "🤖 AI Reports": "ai_reports",
                "👤 My Profile": "profile",
            }

        # Use session_state to track current page
        if "current_page" not in st.session_state:
            # Default page per role
            defaults = {
                "requester": "requester_dashboard",
                "technician": "technician_queue",
                "admin": "admin_dashboard",
            }
            st.session_state["current_page"] = defaults.get(role, "requester_dashboard")

        for label, page_key in pages.items():
            is_active = st.session_state.get("current_page") == page_key
            button_type = "primary" if is_active else "secondary"
            if st.button(label, key=f"nav_{page_key}", use_container_width=True, type=button_type):
                st.session_state["current_page"] = page_key
                st.rerun()

        st.divider()

        if st.button("🚪 Logout", use_container_width=True, type="secondary"):
            logout_user()
            st.session_state.pop("current_page", None)
            st.rerun()

        st.caption(f"v1.0.0 · {settings.APP_ENV.title()}")

    return st.session_state.get("current_page", "requester_dashboard")


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

def show_success(message: str) -> None:
    st.success(f"✅ {message}")


def show_error(message: str) -> None:
    st.error(f"❌ {message}")


def show_warning(message: str) -> None:
    st.warning(f"⚠️ {message}")


def show_info(message: str) -> None:
    st.info(f"ℹ️ {message}")


# ---------------------------------------------------------------------------
# Reusable UI atoms
# ---------------------------------------------------------------------------

def status_badge(status: str) -> str:
    """Return an HTML badge string for a request status."""
    colour = STATUS_COLOURS.get(status, "#6b7280")
    emoji = STATUS_EMOJI.get(status, "")
    label = f"{emoji} {status.replace('_', ' ').title()}"
    return f"<span class='badge' style='background:{colour};'>{label}</span>"


def priority_badge(priority: str) -> str:
    """Return an HTML badge string for a request priority."""
    colour = PRIORITY_COLOURS.get(priority, "#6b7280")
    emoji = PRIORITY_EMOJI.get(priority, "")
    label = f"{emoji} {priority.title()}"
    return f"<span class='badge' style='background:{colour};'>{label}</span>"


def render_kpi_row(metrics: list[dict]) -> None:
    """
    Render a row of KPI metric cards.

    Parameters
    ----------
    metrics : list of dicts, each with keys:
        - label  : str
        - value  : int | float | str
        - delta  : str | None  (optional, e.g. "+5 this week")
        - help   : str | None
    """
    cols = st.columns(len(metrics))
    for col, m in zip(cols, metrics):
        with col:
            st.metric(
                label=m["label"],
                value=m["value"],
                delta=m.get("delta"),
                help=m.get("help"),
            )


def render_page_title(title: str, subtitle: str = "") -> None:
    st.markdown(f"## {title}")
    if subtitle:
        st.caption(subtitle)
    st.divider()


def confirm_action(key: str, prompt: str) -> bool:
    """
    Render a checkbox-based confirmation guard.
    Returns True only when the checkbox is checked.
    """
    return st.checkbox(prompt, key=key, value=False)


def render_empty_state(icon: str, message: str) -> None:
    """Display a centered empty-state panel with an icon and message."""
    st.markdown(
        f"<div class='empty-state'>"
        f"<div class='empty-state-icon'>{icon}</div>"
        f"<div>{message}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_section_header(title: str) -> None:
    """Display a styled section header for grouping dashboard content."""
    st.markdown(f"<div class='section-header'>{title}</div>", unsafe_allow_html=True)
