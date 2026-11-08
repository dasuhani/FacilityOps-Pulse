"""
app/pages/requester.py
-----------------------
Requester role pages:
  - requester_dashboard : list of own requests with filters + KPIs
  - submit_request      : new request submission form with location picker,
                          category dropdown, and AI analysis
  - profile             : view and update own profile / change password

Requester capabilities:
  - Create a new request (title, description, location, category)
  - View submitted requests
  - View request details with full status history and comments
  - Track request status
  - Read technician and administrator comments
  - Cancel submitted requests (before assignment)
  - Add comments to their own requests
"""

import streamlit as st

from business.request_service import (
    submit_request,
    get_requests_for_requester_view,
    get_request_detail,
    get_active_locations,
    check_for_similar_requests,
    cancel_request,
    add_request_comment,
)
from business.analytics_service import get_recent_requests_for_requester
from business.user_service import update_own_profile, change_own_password
from database.models.request import (
    RequestCategory,
    RequestPriority,
    RequestStatus,
    ACTIVE_STATUSES,
    CATEGORY_LABELS,
    PRIORITY_LABELS,
    STATUS_LABELS,
)
from app.components.layout import (
    render_page_title, show_success, show_error, show_info, show_warning,
    render_kpi_row, render_empty_state, render_section_header,
)
from app.components.tables import (
    render_requests_table,
    render_request_detail_card,
    render_status_history,
    render_similar_requests_warning,
)
from core.security import get_current_user


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def render_dashboard() -> None:
    user = get_current_user()
    render_page_title("📋 My Requests", f"Welcome, {user['full_name']}")

    # --- Filters ---
    col_f1, col_f2, col_f3, _ = st.columns([1, 1, 1, 1])
    with col_f1:
        status_options = ["All"] + [s.value for s in RequestStatus]
        status_filter = st.selectbox(
            "Filter by Status", status_options,
            key="req_status_filter",
            format_func=lambda s: s if s == "All" else STATUS_LABELS.get(RequestStatus(s), s),
        )
    with col_f2:
        priority_options = ["All"] + [p.value for p in RequestPriority]
        priority_filter = st.selectbox(
            "Filter by Priority", priority_options,
            key="req_priority_filter",
            format_func=lambda p: p if p == "All" else PRIORITY_LABELS.get(RequestPriority(p), p),
        )
    with col_f3:
        if st.button("🔄 Refresh", key="req_refresh"):
            st.rerun()

    status_list = None if status_filter == "All" else [status_filter]

    with st.spinner("Loading your requests…"):
        requests = get_requests_for_requester_view(
            requester_id=user["id"],
            status_filter=status_list,
        )
        recent_requests = get_recent_requests_for_requester(user["id"], limit=5)

    # Apply priority filter in Python
    if priority_filter != "All":
        requests = [r for r in requests if r["priority"] == priority_filter]

    # --- KPI row ---
    total = len(requests)
    open_count = sum(1 for r in requests if r["status"] in ("submitted", "open", "assigned"))
    in_progress_count = sum(1 for r in requests if r["status"] in ("in_progress", "on_hold"))
    resolved_count = sum(1 for r in requests if r["status"] in ("resolved", "closed"))
    cancelled_count = sum(1 for r in requests if r["status"] == "cancelled")

    render_kpi_row([
        {"label": "My Total Requests", "value": total},
        {"label": "Open", "value": open_count,
         "help": "Submitted or assigned — not yet started"},
        {"label": "In Progress", "value": in_progress_count,
         "help": "Being worked on or on hold"},
        {"label": "Resolved / Closed", "value": resolved_count},
        {"label": "Cancelled", "value": cancelled_count},
    ])

    # --- Empty state ---
    if total == 0:
        st.divider()
        render_empty_state("📭", "You have no requests matching the current filters. "
                           "Submit a new request to get started.")
        st.markdown("### ➕ Submit a New Request")
        if st.button("➕ Create Request", key="req_empty_submit", type="primary"):
            st.session_state["current_page"] = "submit_request"
            st.rerun()
        return

    # --- Recent Request Updates ---
    if recent_requests:
        st.divider()
        render_section_header("🕐 Recent Updates")
        recent_rows = []
        for r in recent_requests[:5]:
            updated = r.get("updated_at", r.get("created_at", ""))
            updated_str = updated[:16].replace("T", " ") if updated else "—"
            tech_name = r.get("technician_name") or "Unassigned"
            recent_rows.append({
                "Ref #": r.get("reference_number", "—"),
                "Title": (r.get("title", "") or "")[:45],
                "Status": STATUS_LABELS.get(RequestStatus(r.get("status", "open")), r.get("status", "—")),
                "Priority": PRIORITY_LABELS.get(RequestPriority(r.get("priority", "medium")), r.get("priority", "—")),
                "Technician": tech_name,
                "Updated": updated_str,
            })
        if recent_rows:
            import pandas as pd
            st.dataframe(pd.DataFrame(recent_rows), use_container_width=True, hide_index=True)

    # --- Request Table ---
    st.divider()
    render_section_header("📋 My Requests")

    selected = render_requests_table(
        requests,
        show_requester=False,
        show_technician=True,
        selectable=True,
        key="req_table_select",
    )

    if selected:
        st.divider()
        _render_request_detail_panel(selected, user)


def _render_request_detail_panel(req_summary: dict, user: dict) -> None:
    """Detail panel shown when a requester selects a row."""
    with st.spinner("Loading request details…"):
        detail = get_request_detail(req_summary["id"])

    if not detail:
        show_error("Could not load request details.")
        return

    render_request_detail_card(detail)

    # --- Comments section ---
    _render_comments_section(detail, user)

    # --- History ---
    with st.expander("📅 Status History", expanded=False):
        render_status_history(detail.get("history", []))

    # --- Full request history (v2) ---
    if detail.get("request_history"):
        with st.expander("📜 Full Change Log", expanded=False):
            _render_full_history(detail["request_history"])

    # --- Cancel action — only for SUBMITTED/OPEN requests ---
    cancellable_statuses = {RequestStatus.SUBMITTED.value, RequestStatus.OPEN.value}
    if detail["status"] in cancellable_statuses:
        st.divider()
        st.markdown("**Actions**")
        if st.button(
            "❌ Cancel This Request",
            key=f"cancel_req_{detail['id']}",
            type="secondary",
        ):
            st.session_state[f"confirm_cancel_{detail['id']}"] = True

        if st.session_state.get(f"confirm_cancel_{detail['id']}"):
            st.warning(
                "Are you sure you want to cancel this request? "
                "This cannot be undone."
            )
            col_yes, col_no, _ = st.columns([1, 1, 3])
            with col_yes:
                if st.button("Yes, Cancel", key=f"yes_cancel_{detail['id']}", type="primary"):
                    result = cancel_request(detail["id"], user["id"])
                    if result["success"]:
                        show_success("Request cancelled successfully.")
                        st.session_state.pop(f"confirm_cancel_{detail['id']}", None)
                        st.rerun()
                    else:
                        show_error(result["error"])
            with col_no:
                if st.button("No, Keep It", key=f"no_cancel_{detail['id']}"):
                    st.session_state.pop(f"confirm_cancel_{detail['id']}", None)
                    st.rerun()


def _render_comments_section(detail: dict, user: dict) -> None:
    """Display comments and allow the requester to add one."""
    st.markdown("#### 💬 Comments")

    comments = detail.get("comments", [])
    if comments:
        for c in comments:
            role_tag = ""
            # Infer role from comment context
            if c["user_id"] != detail.get("requester_id"):
                role_tag = " 🔧 Technician" if c["user_id"] == detail.get("technician_id") else " 🛡️ Admin"
            else:
                role_tag = " 👤 You"

            st.markdown(
                f"**{c['user_name']}**{role_tag} "
                f"<span style='color:#9ca3af; font-size:0.8rem;'>"
                f"— {c['created_at'][:16].replace('T', ' ') if c['created_at'] else ''}</span>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='margin-left:16px; margin-bottom:12px;'>{c['comment']}</div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("No comments yet.")

    # Add comment form
    with st.form(f"req_comment_form_{detail['id']}", clear_on_submit=True):
        new_comment = st.text_area(
            "Add a Comment",
            placeholder="Add a note or question about this request…",
            height=80,
            max_chars=4000,
        )
        submitted = st.form_submit_button("💬 Post Comment", type="secondary")

    if submitted:
        if not new_comment.strip():
            show_error("Comment must not be empty.")
            return
        result = add_request_comment(
            request_id=detail["id"],
            user_id=user["id"],
            comment=new_comment,
            user_role="requester",
        )
        if result["success"]:
            show_success("Comment posted.")
            st.rerun()
        else:
            show_error(result["error"])


def _render_full_history(history: list[dict]) -> None:
    """Render the v2 RequestHistory table entries."""
    if not history:
        st.caption("No change log entries.")
        return

    for entry in history:
        event_type = entry.get("event_type", "").replace("_", " ").title()
        actor = entry.get("actor_name", "System")
        ts = (entry.get("created_at") or "")[:16].replace("T", " ")

        detail_parts = []
        if entry.get("old_status") and entry.get("new_status"):
            detail_parts.append(
                f"{entry['old_status']} → {entry['new_status']}"
            )
        if entry.get("field_name"):
            detail_parts.append(f"Field: {entry['field_name']}")
        if entry.get("old_value") and entry.get("new_value"):
            detail_parts.append(f"{entry['old_value']} → {entry['new_value']}")
        if entry.get("note"):
            detail_parts.append(entry["note"])

        detail_str = " | ".join(detail_parts) if detail_parts else ""
        st.markdown(
            f"**{ts}** — {event_type} *(by {actor})*"
            + (f"<br/>{detail_str}" if detail_str else ""),
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Submit Request
# ---------------------------------------------------------------------------

def render_submit_request() -> None:
    render_page_title("➕ Submit New Request", "Describe your facility or IT issue below.")
    user = get_current_user()

    # Step 1 — Check for similar requests before showing the full form
    _render_similarity_check()

    st.divider()
    _render_submission_form(user)


def _render_similarity_check() -> None:
    with st.expander("🔍 Check for Similar Existing Requests (optional)", expanded=False):
        st.caption(
            "Enter a brief title and description to see if a similar request "
            "already exists before submitting."
        )
        check_title = st.text_input(
            "Quick Title Check",
            key="sim_check_title",
            placeholder="e.g. Air conditioning not working in Room 204",
        )
        check_desc = st.text_area(
            "Brief Description",
            key="sim_check_desc",
            placeholder="e.g. The AC unit has been making noise and not cooling since Monday.",
            height=80,
        )
        if st.button("🔍 Check for Duplicates", key="sim_check_btn"):
            if check_title.strip() and check_desc.strip():
                with st.spinner("Searching for similar requests…"):
                    similar = check_for_similar_requests(check_title, check_desc)
                if similar:
                    render_similar_requests_warning(similar)
                else:
                    st.success("✅ No similar requests found. You can proceed with submission.")
            else:
                show_warning("Enter both a title and description to check for duplicates.")


def _render_submission_form(user: dict) -> None:
    st.markdown("### Request Details")

    # Load active locations for the dropdown
    locations = get_active_locations()

    with st.form("submit_request_form", clear_on_submit=False):
        # Basic info
        title = st.text_input(
            "Request Title *",
            placeholder="Short, descriptive title (e.g. 'Leaking pipe in 3rd floor restroom')",
            max_chars=256,
        )

        description = st.text_area(
            "Description *",
            placeholder=(
                "Describe the issue in detail: what is happening, when it started, "
                "how it is affecting your work, and any steps already taken."
            ),
            height=140,
            max_chars=4000,
        )

        # Category selection — all 10 categories
        category = st.selectbox(
            "Category *",
            options=list(RequestCategory),
            format_func=lambda c: CATEGORY_LABELS.get(c, c.value.title()),
            index=list(RequestCategory).index(RequestCategory.OTHER),
        )

        # Location selection — structured dropdown + free-text fallback
        st.markdown("**Location ***")
        use_structured = st.radio(
            "Location entry mode:",
            options=["Select from list", "Enter manually"],
            horizontal=True,
            key="loc_mode",
            label_visibility="collapsed",
        )

        location_id = None
        location_text = ""
        building = ""
        floor_or_room = ""

        if use_structured == "Select from list" and locations:
            loc_options = {l["display_name"]: l for l in locations}
            selected_loc_label = st.selectbox(
                "Choose a location",
                options=list(loc_options.keys()),
                index=None,
                placeholder="Select building / floor / area…",
                key="loc_select",
            )
            if selected_loc_label:
                selected_loc = loc_options[selected_loc_label]
                location_id = selected_loc["id"]
                location_text = selected_loc["display_name"]
                building = selected_loc.get("building_name", "")
                floor_or_room = selected_loc.get("floor", "")
            # Allow building/floor override
            col_b, col_f = st.columns(2)
            with col_b:
                building = st.text_input(
                    "Building (auto-filled, editable)",
                    value=building,
                    max_chars=128,
                    key="req_building",
                )
            with col_f:
                floor_or_room = st.text_input(
                    "Floor / Room (auto-filled, editable)",
                    value=floor_or_room or "",
                    max_chars=64,
                    key="req_floor",
                )
        else:
            if not locations:
                show_info(
                    "No predefined locations available. "
                    "Please enter the location manually."
                )
            location_text = st.text_input(
                "Location *",
                placeholder="e.g. Building A, 3rd Floor, Room 302",
                max_chars=256,
                key="req_location_manual",
            )
            col_b, col_f = st.columns(2)
            with col_b:
                building = st.text_input(
                    "Building",
                    placeholder="e.g. Main HQ (optional)",
                    max_chars=128,
                    key="req_building_manual",
                )
            with col_f:
                floor_or_room = st.text_input(
                    "Floor / Room",
                    placeholder="e.g. Floor 3, Room 204 (optional)",
                    max_chars=64,
                    key="req_floor_manual",
                )

        priority = st.selectbox(
            "Priority",
            options=list(RequestPriority),
            format_func=lambda p: PRIORITY_LABELS.get(p, p.value.title()),
            index=list(RequestPriority).index(RequestPriority.MEDIUM),
            help=(
                "AI will recommend a priority based on your description. "
                "You may choose a different level here and it will be respected "
                "unless the AI detects a critical safety issue."
            ),
        )

        run_ai = st.checkbox(
            "🤖 Run AI Classification & Priority Analysis",
            value=True,
            help=(
                "When enabled, the AI will automatically categorise your request "
                "and recommend a priority level. Requires a Groq API key."
            ),
        )

        submitted = st.form_submit_button(
            "📤 Submit Request",
            use_container_width=True,
            type="primary",
        )

    if submitted:
        _process_submission(
            user=user,
            title=title,
            description=description,
            location=location_text,
            building=building,
            floor_or_room=floor_or_room,
            category=category,
            priority=priority,
            location_id=location_id,
            run_ai=run_ai,
        )


def _process_submission(
    user, title, description, location, building,
    floor_or_room, category, priority, location_id, run_ai,
) -> None:
    with st.spinner("Submitting your request and running AI analysis…"):
        result = submit_request(
            requester_id=user["id"],
            title=title,
            description=description,
            location=location,
            category=category,
            priority=priority,
            building=building or None,
            floor_or_room=floor_or_room or None,
            location_id=location_id,
            run_ai=run_ai,
        )

    if not result["success"]:
        for err in result["errors"]:
            show_error(err)
        return

    ref = result["reference_number"]
    show_success(f"Request submitted successfully! Reference: **{ref}**")

    # Display AI results
    ai_class = result.get("ai_classification")
    ai_prio = result.get("ai_priority")

    if ai_class and ai_class.succeeded:
        with st.expander("🤖 AI Classification Results", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Detected Category:** {ai_class.category.title()}")
                st.markdown(f"**Sub-category:** {ai_class.sub_category or '—'}")
                st.markdown(f"**Recommended Department:** {ai_class.department or '—'}")
                conf_pct = f"{ai_class.confidence * 100:.0f}%"
                st.markdown(f"**Confidence:** {conf_pct}")
            with col2:
                if ai_prio and ai_prio.succeeded:
                    st.markdown(f"**AI Priority:** {ai_prio.priority.title()}")
                    if ai_prio.escalation_flag:
                        st.error("🚨 Escalation Flag: This request may involve a safety or compliance risk.")
                    st.markdown(f"**Justification:** {ai_prio.justification}")
            if ai_class.notes:
                st.caption(f"📝 {ai_class.notes}")
    elif run_ai:
        show_info(
            "AI analysis was not available for this request. "
            "Your request was submitted with the priority and category you selected."
        )

    st.divider()
    st.markdown(
        "**What's next?** Your request is now **Submitted** and in the queue. "
        "An administrator will review and assign it to a technician."
    )

    if st.button("➕ Submit Another Request", key="submit_another"):
        st.rerun()


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def render_profile() -> None:
    user = get_current_user()
    render_page_title("👤 My Profile", "Manage your account details.")

    tab_info, tab_password = st.tabs(["📋 Profile Information", "🔑 Change Password"])

    with tab_info:
        _render_profile_info(user)

    with tab_password:
        _render_change_password(user)


def _render_profile_info(user: dict) -> None:
    st.markdown("#### Update Profile")

    with st.form("profile_form"):
        col1, col2 = st.columns(2)
        with col1:
            full_name = st.text_input("Full Name", value=user.get("full_name", ""))
            email = st.text_input("Email", value=user.get("email", ""))
        with col2:
            department = st.text_input("Department", value=user.get("department") or "")
            phone = st.text_input("Phone", value=user.get("phone") or "")

        submitted = st.form_submit_button("💾 Save Changes", type="primary")

    if submitted:
        result = update_own_profile(
            user_id=user["id"],
            full_name=full_name or None,
            email=email or None,
            department=department or None,
            phone=phone or None,
        )
        if result["success"]:
            show_success("Profile updated successfully. Please log out and back in to see changes.")
        else:
            show_error(result["error"])

    # Read-only info
    st.divider()
    st.markdown("#### Account Information")
    col1, col2, col3 = st.columns(3)
    col1.markdown(f"**Username:** `{user.get('username', '—')}`")
    col2.markdown(f"**Role:** {user.get('role', '—').title()}")
    col3.markdown(f"**Member since:** {user.get('created_at', '—')[:10] if user.get('created_at') else '—'}")


def _render_change_password(user: dict) -> None:
    st.markdown("#### Change Password")

    with st.form("change_password_form", clear_on_submit=True):
        current_password = st.text_input("Current Password", type="password")
        new_password = st.text_input(
            "New Password",
            type="password",
            help="Min 8 chars, uppercase, lowercase, digit, special character.",
        )
        confirm_password = st.text_input("Confirm New Password", type="password")
        submitted = st.form_submit_button("🔑 Change Password", type="primary")

    if submitted:
        result = change_own_password(
            user_id=user["id"],
            current_password=current_password,
            new_password=new_password,
            confirm_new_password=confirm_password,
        )
        if result["success"]:
            show_success("Password changed successfully.")
        else:
            show_error(result["error"])
