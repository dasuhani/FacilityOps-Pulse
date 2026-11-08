"""
app/pages/technician.py
------------------------
Technician role pages:
  - technician_queue : work queue of assigned requests with status/priority filters
  - profile          : technician's own profile / change password

Technician capabilities:
  - View assigned requests (only requests assigned to them)
  - Filter requests by status and priority
  - Open request details
  - Add progress comments
  - Change status to In Progress
  - Mark work as Resolved (requires resolution notes)
  - Put request On Hold (with reason note)
  - View request history (full change log)
  - Read requester and admin comments
"""

import streamlit as st

from business.request_service import (
    get_requests_for_technician_view,
    get_request_detail,
    technician_update_status,
    add_request_comment,
)
from business.analytics_service import (
    get_recent_requests_for_technician,
    SLA_HOURS,
)
from business.user_service import update_own_profile, change_own_password
from database.models.request import (
    RequestStatus,
    RequestPriority,
    ACTIVE_STATUSES,
    PRIORITY_LABELS,
    STATUS_LABELS,
)
from app.components.layout import (
    render_page_title, show_success, show_error, show_info,
    render_kpi_row, render_empty_state, render_section_header,
)
from app.components.tables import (
    render_requests_table,
    render_request_detail_card,
    render_status_history,
)
from core.security import get_current_user


# ---------------------------------------------------------------------------
# Technician Work Queue
# ---------------------------------------------------------------------------

def render_queue() -> None:
    user = get_current_user()
    render_page_title(
        "🔧 My Work Queue",
        f"Requests assigned to you, {user['full_name']}.",
    )

    # --- Filters ---
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    with col_f1:
        status_options = ["Active Only", "All Statuses"]
        view_mode = st.selectbox("View", status_options, key="tech_view_mode")
    with col_f2:
        priority_options = ["All"] + [p.value for p in RequestPriority]
        priority_filter = st.selectbox(
            "Filter by Priority", priority_options,
            key="tech_priority_filter",
            format_func=lambda p: p if p == "All" else PRIORITY_LABELS.get(RequestPriority(p), p),
        )
    with col_f3:
        status_filter_opts = ["All"] + [s.value for s in RequestStatus]
        status_filter = st.selectbox(
            "Filter by Status", status_filter_opts, key="tech_status_filter",
            format_func=lambda s: s if s == "All" else STATUS_LABELS.get(RequestStatus(s), s),
        )
    with col_f4:
        if st.button("🔄 Refresh", key="tech_refresh"):
            st.rerun()

    # Determine status filter
    if view_mode == "Active Only" and status_filter == "All":
        status_filter_list = [
            RequestStatus.ASSIGNED.value,
            RequestStatus.IN_PROGRESS.value,
            RequestStatus.ON_HOLD.value,
            RequestStatus.SUBMITTED.value,
        ]
    elif status_filter != "All":
        status_filter_list = [status_filter]
    else:
        status_filter_list = None

    with st.spinner("Loading your work queue…"):
        requests = get_requests_for_technician_view(
            technician_id=user["id"],
            status_filter=status_filter_list,
        )
        recent_requests = get_recent_requests_for_technician(user["id"], limit=5)

    # Apply priority filter in Python
    if priority_filter != "All":
        requests = [r for r in requests if r["priority"] == priority_filter]

    # --- KPI Cards ---
    total = len(requests)
    open_assigned = sum(1 for r in requests if r["status"] in ("assigned", "submitted"))
    in_prog = sum(1 for r in requests if r["status"] == "in_progress")
    high_priority = sum(1 for r in requests if r["priority"] in ("high", "critical"))
    critical_count = sum(1 for r in requests if r["priority"] == "critical")
    on_hold = sum(1 for r in requests if r["status"] == "on_hold")

    # Calculate overdue (simplified: active requests older than SLA threshold)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    overdue = 0
    for r in requests:
        if r["status"] in ("assigned", "in_progress", "on_hold", "submitted"):
            created = r.get("created_at", "")
            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    age_hours = (now - created_dt).total_seconds() / 3600
                    sla = SLA_HOURS.get(r["priority"], 24)
                    if age_hours > sla:
                        overdue += 1
                except (ValueError, TypeError):
                    pass

    render_kpi_row([
        {"label": "Assigned to Me", "value": total},
        {"label": "Open / Assigned", "value": open_assigned,
         "help": "Assigned but not yet started"},
        {"label": "In Progress", "value": in_prog},
        {"label": "High / Critical", "value": high_priority,
         "help": f"Critical: {critical_count}, High: {high_priority - critical_count}"},
        {"label": "Overdue", "value": overdue,
         "help": "Requests past their SLA threshold"},
        {"label": "On Hold", "value": on_hold},
    ])

    # --- Empty state ---
    if total == 0:
        st.divider()
        render_empty_state("📭", "You have no assigned requests matching the current filters. "
                           "Check back later or adjust your filters.")
        return

    # --- Recently Updated Requests ---
    if recent_requests:
        st.divider()
        render_section_header("🕐 Recently Updated")
        recent_rows = []
        for r in recent_requests[:5]:
            updated = r.get("updated_at", r.get("created_at", ""))
            updated_str = updated[:16].replace("T", " ") if updated else "—"
            recent_rows.append({
                "Ref #": r.get("reference_number", "—"),
                "Title": (r.get("title", "") or "")[:45],
                "Status": STATUS_LABELS.get(RequestStatus(r.get("status", "open")), r.get("status", "—")),
                "Priority": PRIORITY_LABELS.get(RequestPriority(r.get("priority", "medium")), r.get("priority", "—")),
                "Updated": updated_str,
            })
        if recent_rows:
            import pandas as pd
            st.dataframe(pd.DataFrame(recent_rows), use_container_width=True, hide_index=True)

    # --- Workload Summary ---
    st.divider()
    render_section_header("📊 Workload Summary")
    wl_col1, wl_col2, wl_col3 = st.columns(3)
    with wl_col1:
        st.metric("Active Workload", total - on_hold, help="Total minus on-hold")
    with wl_col2:
        st.metric("High Priority Items", high_priority)
    with wl_col3:
        st.metric("Items On Hold", on_hold)

    # --- Request Table ---
    st.divider()
    render_section_header("📋 Request Queue")

    selected = render_requests_table(
        requests,
        show_requester=True,
        show_technician=False,
        selectable=True,
        key="tech_table_select",
    )

    if selected:
        st.divider()
        _render_work_panel(selected, user)


def _render_work_panel(req_summary: dict, user: dict) -> None:
    """Detail + update panel for a selected assigned request."""
    with st.spinner("Loading request details…"):
        detail = get_request_detail(req_summary["id"])

    if not detail:
        show_error("Could not load request details.")
        return

    render_request_detail_card(detail)

    st.divider()

    # Technicians can update status for non-terminal requests
    terminal_statuses = {"resolved", "closed", "cancelled"}
    if detail["status"] in terminal_statuses:
        show_info(f"This request is **{detail['status']}** and cannot be updated further.")

        # Still show comments and history
        _render_comments_section(detail, user)
        with st.expander("📅 Status History", expanded=False):
            render_status_history(detail.get("history", []))
        if detail.get("request_history"):
            with st.expander("📜 Full Change Log", expanded=False):
                _render_full_history(detail["request_history"])
        return

    # --- Update panel with tabs ---
    tab_update, tab_comments, tab_history = st.tabs([
        "✏️ Update Status",
        "💬 Comments",
        "📅 History",
    ])

    with tab_update:
        _render_status_update_form(detail, user)

    with tab_comments:
        _render_comments_section(detail, user)

    with tab_history:
        render_status_history(detail.get("history", []))
        if detail.get("request_history"):
            st.markdown("##### Full Change Log")
            _render_full_history(detail["request_history"])


def _render_status_update_form(detail: dict, user: dict) -> None:
    """Form for the technician to update request status."""

    # Determine which statuses are valid transitions from current
    current = detail["status"]
    allowed_map = {}

    if current == "assigned":
        allowed_map = {
            RequestStatus.IN_PROGRESS.value: "🔧 Start Work (In Progress)",
            RequestStatus.ON_HOLD.value: "⏸️ Put On Hold",
        }
    elif current == "in_progress":
        allowed_map = {
            RequestStatus.RESOLVED.value: "✅ Mark Resolved",
            RequestStatus.ON_HOLD.value: "⏸️ Put On Hold",
        }
    elif current == "on_hold":
        allowed_map = {
            RequestStatus.IN_PROGRESS.value: "🔧 Resume Work",
            RequestStatus.RESOLVED.value: "✅ Mark Resolved",
        }
    elif current == "submitted" or current == "open":
        # Legacy/open — treat like assigned
        allowed_map = {
            RequestStatus.IN_PROGRESS.value: "🔧 Start Work (In Progress)",
            RequestStatus.ON_HOLD.value: "⏸️ Put On Hold",
        }
    else:
        allowed_map = {
            RequestStatus.IN_PROGRESS.value: "🔧 In Progress",
            RequestStatus.ON_HOLD.value: "⏸️ On Hold",
            RequestStatus.RESOLVED.value: "✅ Resolved",
        }

    with st.form(f"tech_update_{detail['id']}", clear_on_submit=False):
        st.markdown(f"**Current status:** {STATUS_LABELS.get(RequestStatus(current), current.title())}")

        new_status = st.selectbox(
            "New Status *",
            options=list(allowed_map.keys()),
            format_func=lambda s: allowed_map[s],
            index=0,
        )

        work_note = st.text_area(
            "Progress Note",
            placeholder=(
                "Describe the work performed, findings, or reason for the status change. "
                "This note will appear in the request history."
            ),
            height=100,
            max_chars=1000,
        )

        resolution_notes = ""
        if new_status == RequestStatus.RESOLVED.value:
            resolution_notes = st.text_area(
                "Resolution Notes *",
                placeholder="Describe how the issue was resolved, parts used, actions taken.",
                height=120,
                max_chars=2000,
                help="Required when marking a request as resolved.",
            )

        submitted = st.form_submit_button("💾 Save Update", type="primary", use_container_width=True)

    if submitted:
        if new_status == RequestStatus.RESOLVED.value and not resolution_notes.strip():
            show_error("Resolution notes are required when marking a request as Resolved.")
            return

        result = technician_update_status(
            request_id=detail["id"],
            new_status=new_status,
            technician_id=user["id"],
            note=work_note or None,
            resolution_notes=resolution_notes or None,
        )

        if result["success"]:
            show_success("Request updated successfully.")
            st.rerun()
        else:
            show_error(result["error"])


def _render_comments_section(detail: dict, user: dict) -> None:
    """Display all comments and allow the technician to add a progress comment."""
    st.markdown("#### 💬 Comments")

    comments = detail.get("comments", [])
    if comments:
        for c in comments:
            # Determine role tag
            if c["user_id"] == detail.get("requester_id"):
                role_tag = " 👤 Requester"
            elif c["user_id"] == detail.get("technician_id"):
                role_tag = " 🔧 You" if c["user_id"] == user["id"] else " 🔧 Technician"
            else:
                role_tag = " 🛡️ Admin"

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
    with st.form(f"tech_comment_form_{detail['id']}", clear_on_submit=True):
        new_comment = st.text_area(
            "Add a Progress Comment",
            placeholder="Add a work update, finding, or note about this request…",
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
            user_role="technician",
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
            detail_parts.append(f"{entry['old_status']} → {entry['new_status']}")
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
# Profile
# ---------------------------------------------------------------------------

def render_profile() -> None:
    user = get_current_user()
    render_page_title("👤 My Profile", "Manage your account details.")

    tab_info, tab_password = st.tabs(["📋 Profile Information", "🔑 Change Password"])

    with tab_info:
        with st.form("tech_profile_form"):
            col1, col2 = st.columns(2)
            with col1:
                full_name = st.text_input("Full Name", value=user.get("full_name", ""))
                email = st.text_input("Email", value=user.get("email", ""))
            with col2:
                department = st.text_input("Department", value=user.get("department") or "")
                phone = st.text_input("Phone", value=user.get("phone") or "")
            save = st.form_submit_button("💾 Save Changes", type="primary")

        if save:
            result = update_own_profile(
                user_id=user["id"],
                full_name=full_name or None,
                email=email or None,
                department=department or None,
                phone=phone or None,
            )
            if result["success"]:
                show_success("Profile updated. Log out and back in to see changes.")
            else:
                show_error(result["error"])

        st.divider()
        col1, col2 = st.columns(2)
        col1.markdown(f"**Username:** `{user.get('username', '—')}`")
        col2.markdown(f"**Role:** {user.get('role', '—').title()}")

    with tab_password:
        with st.form("tech_password_form", clear_on_submit=True):
            cur_pw = st.text_input("Current Password", type="password")
            new_pw = st.text_input("New Password", type="password")
            conf_pw = st.text_input("Confirm New Password", type="password")
            save_pw = st.form_submit_button("🔑 Change Password", type="primary")

        if save_pw:
            result = change_own_password(
                user_id=user["id"],
                current_password=cur_pw,
                new_password=new_pw,
                confirm_new_password=conf_pw,
            )
            if result["success"]:
                show_success("Password changed successfully.")
            else:
                show_error(result["error"])
