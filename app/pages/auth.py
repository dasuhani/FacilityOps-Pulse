"""
app/pages/auth.py
-----------------
Authentication page: Login and self-registration (Requesters only).
Rendered when no user is in session state.
"""

import streamlit as st

from business.user_service import login, register_requester
from app.components.layout import (
    APP_NAME, APP_ICON, APP_TAGLINE,
    show_success, show_error,
)
from core.config import settings


def render() -> None:
    """Entry point called by app.py when the user is not authenticated."""
    # Centred narrow layout for auth forms
    _, col, _ = st.columns([1, 2, 1])

    with col:
        st.markdown(
            f"<h1 style='text-align:center;'>{APP_ICON} {APP_NAME}</h1>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<p style='text-align:center; color:#9ca3af;'>{APP_TAGLINE}</p>",
            unsafe_allow_html=True,
        )
        st.divider()

        tab_login, tab_register = st.tabs(["🔑 Login", "📝 Register"])

        with tab_login:
            _render_login_form()

        with tab_register:
            _render_register_form()

        st.divider()
        st.caption(
            "Administrators and Technicians are created by a system administrator. "
            "Self-registration is for Requesters only."
        )

        # Show config issues as a collapsible warning (dev mode only)
        if settings.is_development:
            issues = settings.validate()
            if issues:
                with st.expander("⚠️ Configuration Issues Detected", expanded=False):
                    for issue in issues:
                        st.warning(issue)


def _render_login_form() -> None:
    st.markdown("#### Sign In")

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input(
            "Username",
            placeholder="Enter your username",
            autocomplete="username",
        )
        password = st.text_input(
            "Password",
            type="password",
            placeholder="Enter your password",
            autocomplete="current-password",
        )
        submitted = st.form_submit_button(
            "Login", use_container_width=True, type="primary"
        )

    if submitted:
        if not username or not password:
            show_error("Please enter both username and password.")
            return

        with st.spinner("Authenticating…"):
            result = login(username.strip(), password)

        if result["success"]:
            show_success(
                f"Welcome back, {result['user']['full_name']}!"
            )
            st.rerun()
        else:
            show_error(result["error"])


def _render_register_form() -> None:
    st.markdown("#### Create a Requester Account")
    st.caption(
        "Fill in the details below to create your account. "
        "An administrator will need to approve Technician or Admin access."
    )

    with st.form("register_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            full_name = st.text_input("Full Name *", placeholder="Jane Smith")
            username = st.text_input("Username *", placeholder="jsmith")
            department = st.text_input("Department", placeholder="Finance (optional)")

        with col2:
            email = st.text_input("Email Address *", placeholder="jane@example.com")
            phone = st.text_input("Phone", placeholder="+1 555 000 0000 (optional)")

        st.markdown("---")
        col3, col4 = st.columns(2)
        with col3:
            password = st.text_input(
                "Password *",
                type="password",
                placeholder="Min 8 chars, upper, lower, digit, special",
                help=(
                    "Requirements: 8+ characters, at least one uppercase, "
                    "one lowercase, one digit, one special character."
                ),
            )
        with col4:
            confirm_password = st.text_input(
                "Confirm Password *",
                type="password",
                placeholder="Repeat your password",
            )

        submitted = st.form_submit_button(
            "Create Account", use_container_width=True, type="primary"
        )

    if submitted:
        with st.spinner("Creating account…"):
            result = register_requester(
                username=username,
                email=email,
                full_name=full_name,
                plain_password=password,
                confirm_password=confirm_password,
                department=department or None,
                phone=phone or None,
            )

        if result["success"]:
            show_success(
                "Account created successfully! You can now log in using the Login tab."
            )
        else:
            for err in result["errors"]:
                show_error(err)
