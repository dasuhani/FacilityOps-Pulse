"""
app/pages/admin.py
-------------------
Administrator role pages:
  - admin_dashboard  : KPI overview + SLA breach alerts
  - admin_requests   : full request list with assign/status/priority/AI/comments/history
  - admin_users      : user management (create, activate/deactivate, reset pwd, skills)
  - admin_analytics  : detailed charts and operational metrics
  - ai_reports       : AI-generated management report
  - admin_locations  : location management (create, edit, activate/deactivate)
  - profile          : admin's own profile / password

Admin capabilities:
  - View all requests
  - Search and filter requests
  - Assign or reassign technicians
  - Change priority
  - Review AI recommendations (approve/reject)
  - Change request status
  - Add comments
  - View request history (status + full change log)
  - Manage users and technician skills
  - Manage locations
"""

import streamlit as st
import pandas as pd

from business.request_service import (
    get_all_requests_admin,
    get_request_detail,
    admin_update_status,
    admin_override_priority,
    admin_assign_request,
    admin_unassign_request,
    admin_review_ai_recommendation,
    add_request_comment,
)
from business.user_service import (
    admin_list_users,
    admin_list_technicians,
    admin_create_user,
    admin_toggle_user_active,
    admin_do_reset_password,
    update_own_profile,
    change_own_password,
    get_user_role_counts,
)
from business.analytics_service import (
    get_summary_counts,
    get_requests_over_time,
    get_status_distribution,
    get_category_breakdown,
    get_priority_breakdown,
    get_technician_workload,
    get_resolution_time_stats,
    get_sla_breach_requests,
    get_sla_breach_count,
    get_overdue_count,
    get_location_breakdown,
    get_requests_dataframe,
    get_report_metrics,
)
from database.connection import get_db
from database.crud.location_crud import (
    get_all_locations,
    create_location,
    update_location,
    set_location_active,
    get_location_by_id,
)
from database.crud.skill_crud import (
    get_skills_for_technician,
    add_skill,
    remove_skill,
    get_skill_categories_for_technician,
)
from database.models.request import (
    RequestStatus, RequestPriority, RequestCategory,
    STATUS_LABELS, PRIORITY_LABELS, CATEGORY_LABELS,
)
from database.models.technician_skill import SkillCategory
from services.ai.report_generator import generate_operations_report
from app.components.layout import (
    render_page_title, render_kpi_row,
    show_success, show_error, show_info, show_warning,
    render_empty_state, render_section_header,
)
from app.components.tables import (
    render_requests_table,
    render_request_detail_card,
    render_status_history,
    render_users_table,
    render_technician_workload_table,
    render_sla_breach_table,
)
from app.components.charts import (
    status_donut_chart,
    priority_bar_chart,
    category_bar_chart,
    requests_over_time_chart,
    technician_workload_chart,
    resolution_time_histogram,
    priority_status_heatmap,
    location_bar_chart,
    resolution_trend_chart,
)
from core.security import get_current_user
from core.config import settings


# ---------------------------------------------------------------------------
# Admin Dashboard
# ---------------------------------------------------------------------------

def render_dashboard() -> None:
    render_page_title("📊 Operations Dashboard", "Real-time overview of all service requests.")

    with st.spinner("Loading dashboard data…"):
        summary = get_summary_counts()
        user_counts = get_user_role_counts()
        sla_breaches = get_sla_breach_requests()
        full_df = get_requests_dataframe()
        overdue_count = get_overdue_count(full_df)
        resolution_stats = get_resolution_time_stats(days=None)
        sla_count = get_sla_breach_count(full_df)

    # --- Row 1: Primary KPIs (6 cards) ---
    open_count = (
        summary.get("submitted", 0) + summary.get("open", 0)
        + summary.get("assigned", 0) + summary.get("in_progress", 0)
    )
    critical_high = summary["critical"] + summary["high"]
    avg_res = resolution_stats.get("avg_hours")

    render_kpi_row([
        {"label": "Total Requests", "value": summary["total"]},
        {"label": "Open Requests", "value": open_count,
         "help": "Submitted, assigned, in-progress, and on-hold requests"},
        {"label": "Critical + High", "value": critical_high,
         "help": f"Critical: {summary['critical']}, High: {summary['high']}"},
        {"label": "Overdue", "value": overdue_count,
         "help": "Requests past their SLA threshold or due date"},
        {"label": "Resolved", "value": summary.get("resolved", 0)},
        {"label": "Avg Resolution", "value": f"{avg_res:.1f}h" if avg_res else "N/A",
         "help": f"Based on {resolution_stats.get('count', 0)} resolved requests"},
    ])

    st.divider()

    # --- Row 2: User counts + secondary metrics ---
    render_section_header("Platform Users")
    render_kpi_row([
        {"label": "Requesters", "value": user_counts.get("requester", 0)},
        {"label": "Technicians", "value": user_counts.get("technician", 0)},
        {"label": "Admins", "value": user_counts.get("admin", 0)},
        {"label": "On Hold", "value": summary.get("on_hold", 0)},
        {"label": "Cancelled", "value": summary.get("cancelled", 0)},
        {"label": "Closed", "value": summary.get("closed", 0)},
    ])

    st.divider()

    # --- SLA Breach Alerts ---
    render_section_header("🚨 SLA Breach Alerts")
    if sla_breaches is not None and not sla_breaches.empty:
        show_warning(
            f"**{len(sla_breaches)} request(s)** have exceeded their SLA threshold. "
            "Immediate attention required."
        )
        render_sla_breach_table(sla_breaches)
    else:
        st.success("✅ No SLA breaches. All active requests are within their response windows.")

    st.divider()

    # --- Quick Overview Charts ---
    render_section_header("Quick Overview")

    # Check if we have any data at all
    if summary["total"] == 0:
        render_empty_state("📭", "No requests in the system yet. "
                           "Once requests are submitted, charts and metrics will appear here.")
        return

    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.plotly_chart(
            status_donut_chart(get_status_distribution()),
            use_container_width=True,
        )
    with col_c2:
        st.plotly_chart(
            priority_bar_chart(get_priority_breakdown()),
            use_container_width=True,
        )


# ---------------------------------------------------------------------------
# All Requests (Admin)
# ---------------------------------------------------------------------------

def render_requests() -> None:
    render_page_title("📋 All Requests", "View, assign, and manage every service request.")

    # --- Filters ---
    with st.expander("🔍 Filters", expanded=True):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            status_opts = ["All"] + [s.value for s in RequestStatus]
            status_filter = st.selectbox(
                "Status", status_opts, key="adm_status",
                format_func=lambda s: s if s == "All" else STATUS_LABELS.get(RequestStatus(s), s),
            )
        with col2:
            cat_opts = ["All"] + [c.value for c in RequestCategory]
            cat_filter = st.selectbox(
                "Category", cat_opts, key="adm_cat",
                format_func=lambda c: c if c == "All" else CATEGORY_LABELS.get(RequestCategory(c), c),
            )
        with col3:
            pri_opts = ["All"] + [p.value for p in RequestPriority]
            pri_filter = st.selectbox(
                "Priority", pri_opts, key="adm_pri",
                format_func=lambda p: p if p == "All" else PRIORITY_LABELS.get(RequestPriority(p), p),
            )
        with col4:
            search = st.text_input("Search (title/ref/location)", key="adm_search", placeholder="Search…")

    if st.button("🔄 Refresh", key="adm_req_refresh"):
        st.rerun()

    with st.spinner("Loading requests…"):
        requests = get_all_requests_admin(
            status_filter=[status_filter] if status_filter != "All" else None,
            category_filter=cat_filter if cat_filter != "All" else None,
            priority_filter=pri_filter if pri_filter != "All" else None,
            search_query=search.strip() or None,
        )

    st.caption(f"Showing **{len(requests)}** request(s)")

    selected = render_requests_table(
        requests,
        show_requester=True,
        show_technician=True,
        selectable=True,
        key="adm_req_select",
    )

    if selected:
        st.divider()
        _render_admin_request_panel(selected)


def _render_admin_request_panel(req_summary: dict) -> None:
    """Full admin control panel for a selected request with 6 tabs."""
    user = get_current_user()

    with st.spinner("Loading request details…"):
        detail = get_request_detail(req_summary["id"])

    if not detail:
        show_error("Could not load request details.")
        return

    render_request_detail_card(detail)

    st.divider()

    tab_assign, tab_status, tab_priority, tab_ai, tab_comments, tab_history = st.tabs([
        "👤 Assignment",
        "🔄 Status",
        "⚡ Priority",
        "🤖 AI Review",
        "💬 Comments",
        "📅 History",
    ])

    with tab_assign:
        _render_assignment_panel(detail, user)

    with tab_status:
        _render_status_panel(detail, user)

    with tab_priority:
        _render_priority_panel(detail, user)

    with tab_ai:
        _render_ai_review_panel(detail, user)

    with tab_comments:
        _render_admin_comments_section(detail, user)

    with tab_history:
        render_status_history(detail.get("history", []))
        if detail.get("request_history"):
            st.markdown("##### Full Change Log")
            _render_full_history(detail["request_history"])


def _render_assignment_panel(detail: dict, user: dict) -> None:
    """Assign or re-assign a request to a technician."""
    technicians = admin_list_technicians()

    if not technicians:
        show_warning("No active technicians found. Create technician accounts first.")
        return

    tech_options = {t["full_name"]: t["id"] for t in technicians}

    current_tech = detail.get("technician_name")
    if current_tech and current_tech != "Unassigned":
        show_info(f"Currently assigned to: **{current_tech}**")
    else:
        show_info("This request is not currently assigned to any technician.")

    with st.form(f"assign_form_{detail['id']}"):
        selected_tech_name = st.selectbox(
            "Assign to Technician",
            options=list(tech_options.keys()),
            index=None,
            placeholder="Select a technician…",
        )
        notes = st.text_area(
            "Assignment Notes",
            placeholder="Optional: instructions or context for the technician.",
            height=80,
        )
        col1, col2 = st.columns(2)
        with col1:
            assign_btn = st.form_submit_button("✅ Assign", type="primary", use_container_width=True)
        with col2:
            unassign_btn = st.form_submit_button("🗑️ Remove Assignment", use_container_width=True)

    if assign_btn:
        if not selected_tech_name:
            show_error("Please select a technician.")
        else:
            tech_id = tech_options[selected_tech_name]
            result = admin_assign_request(
                request_id=detail["id"],
                technician_id=tech_id,
                admin_id=user["id"],
                assignment_notes=notes or None,
            )
            if result["success"]:
                show_success(f"Request assigned to **{selected_tech_name}**.")
                st.rerun()
            else:
                show_error(result.get("error", "Assignment failed."))

    if unassign_btn:
        if not detail.get("technician_id"):
            show_warning("This request has no current assignment to remove.")
        else:
            result = admin_unassign_request(
                request_id=detail["id"],
                admin_id=user["id"],
            )
            if result["success"]:
                show_success("Assignment removed. Request returned to submitted queue.")
                st.rerun()
            else:
                show_error(result.get("error", "Could not remove assignment."))


def _render_status_panel(detail: dict, user: dict) -> None:
    with st.form(f"status_form_{detail['id']}"):
        st.markdown(
            f"**Current status:** "
            f"{STATUS_LABELS.get(RequestStatus(detail['status']), detail['status'].title())}"
        )
        new_status = st.selectbox(
            "New Status",
            options=[s.value for s in RequestStatus],
            format_func=lambda s: STATUS_LABELS.get(RequestStatus(s), s),
            index=[s.value for s in RequestStatus].index(detail["status"])
            if detail["status"] in [s.value for s in RequestStatus] else 0,
        )
        note = st.text_area(
            "Admin Note",
            placeholder="Optional: reason for this status change.",
            height=80,
        )
        submitted = st.form_submit_button("💾 Update Status", type="primary")

    if submitted:
        result = admin_update_status(
            request_id=detail["id"],
            new_status=new_status,
            admin_id=user["id"],
            note=note or None,
        )
        if result["success"]:
            show_success("Status updated.")
            st.rerun()
        else:
            show_error(result["error"])


def _render_priority_panel(detail: dict, user: dict) -> None:
    with st.form(f"priority_form_{detail['id']}"):
        st.markdown(
            f"**Current priority:** "
            f"{PRIORITY_LABELS.get(RequestPriority(detail['priority']), detail['priority'].title())}"
        )
        new_priority = st.selectbox(
            "New Priority",
            options=[p.value for p in RequestPriority],
            format_func=lambda p: PRIORITY_LABELS.get(RequestPriority(p), p),
            index=[p.value for p in RequestPriority].index(detail["priority"])
            if detail["priority"] in [p.value for p in RequestPriority] else 1,
        )
        submitted = st.form_submit_button("⚡ Override Priority", type="primary")

    if submitted:
        result = admin_override_priority(
            request_id=detail["id"],
            new_priority=new_priority,
            admin_id=user["id"],
        )
        if result["success"]:
            show_success(f"Priority updated to {new_priority.title()}.")
            st.rerun()
        else:
            show_error(result["error"])


def _render_ai_review_panel(detail: dict, user: dict) -> None:
    """Display AI recommendations and allow admin to approve or reject them."""

    ai_cat = detail.get("ai_suggested_category")
    ai_pri = detail.get("ai_suggested_priority")
    ai_notes = detail.get("ai_classification_notes")
    ai_conf = detail.get("ai_confidence_score")

    has_recommendations = bool(ai_cat or ai_pri)

    if not has_recommendations:
        show_info(
            "No AI recommendations available for this request. "
            "AI analysis runs automatically on submission when the Groq API key is configured."
        )
        return

    st.markdown("#### 🤖 AI Analysis Results")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Suggested Category:**")
        if ai_cat:
            try:
                label = CATEGORY_LABELS.get(RequestCategory(ai_cat), ai_cat.title())
            except ValueError:
                label = ai_cat.title()
            st.markdown(f"`{label}`")
        else:
            st.markdown("_Not available_")

        st.markdown(f"**Confidence:** {f'{ai_conf * 100:.0f}%' if ai_conf else '—'}")

    with col2:
        st.markdown("**Suggested Priority:**")
        if ai_pri:
            try:
                label = PRIORITY_LABELS.get(RequestPriority(ai_pri), ai_pri.title())
            except ValueError:
                label = ai_pri.title()
            st.markdown(f"`{label}`")
        else:
            st.markdown("_Not available_")

    if ai_notes:
        st.markdown(f"**AI Notes:** {ai_notes}")

    st.divider()

    # Current actual values for comparison
    st.markdown("**Current values on request:**")
    c1, c2 = st.columns(2)
    with c1:
        try:
            current_cat_label = CATEGORY_LABELS.get(
                RequestCategory(detail["category"]), detail["category"].title()
            )
        except (ValueError, KeyError):
            current_cat_label = detail["category"].title()
        st.markdown(f"Category: `{current_cat_label}`")
    with c2:
        try:
            current_pri_label = PRIORITY_LABELS.get(
                RequestPriority(detail["priority"]), detail["priority"].title()
            )
        except (ValueError, KeyError):
            current_pri_label = detail["priority"].title()
        st.markdown(f"Priority: `{current_pri_label}`")

    st.divider()

    # Approve / Reject buttons
    st.markdown("#### Review Actions")

    review_note = st.text_area(
        "Review Note (optional)",
        placeholder="Optional: explain your decision.",
        height=60,
        key=f"ai_review_note_{detail['id']}",
    )

    col_a, col_b, col_c, _ = st.columns(4)

    with col_a:
        if st.button("✅ Approve All", key=f"ai_approve_all_{detail['id']}", type="primary",
                      use_container_width=True):
            result = admin_review_ai_recommendation(
                request_id=detail["id"],
                admin_id=user["id"],
                action="approve_all",
                notes=review_note or None,
            )
            if result["success"]:
                show_success("All AI recommendations approved and applied.")
                st.rerun()
            else:
                show_error(result["error"])

    with col_b:
        if st.button("📁 Approve Category", key=f"ai_approve_cat_{detail['id']}",
                      use_container_width=True):
            result = admin_review_ai_recommendation(
                request_id=detail["id"],
                admin_id=user["id"],
                action="approve_category",
                notes=review_note or None,
            )
            if result["success"]:
                show_success("AI category recommendation applied.")
                st.rerun()
            else:
                show_error(result["error"])

    with col_c:
        if st.button("⚡ Approve Priority", key=f"ai_approve_pri_{detail['id']}",
                      use_container_width=True):
            result = admin_review_ai_recommendation(
                request_id=detail["id"],
                admin_id=user["id"],
                action="approve_priority",
                notes=review_note or None,
            )
            if result["success"]:
                show_success("AI priority recommendation applied.")
                st.rerun()
            else:
                show_error(result["error"])

    st.divider()

    if st.button("❌ Reject AI Recommendations", key=f"ai_reject_{detail['id']}",
                 type="secondary", use_container_width=True):
        result = admin_review_ai_recommendation(
            request_id=detail["id"],
            admin_id=user["id"],
            action="reject",
            notes=review_note or None,
        )
        if result["success"]:
            show_info("AI recommendations rejected. The request retains its current values.")
            st.rerun()
        else:
            show_error(result["error"])


def _render_admin_comments_section(detail: dict, user: dict) -> None:
    """Display all comments and allow admin to add one."""
    st.markdown("#### 💬 Comments")

    comments = detail.get("comments", [])
    if comments:
        for c in comments:
            # Determine role tag
            if c["user_id"] == detail.get("requester_id"):
                role_tag = " 👤 Requester"
            elif c["user_id"] == detail.get("technician_id"):
                role_tag = " 🔧 Technician"
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
    with st.form(f"adm_comment_form_{detail['id']}", clear_on_submit=True):
        new_comment = st.text_area(
            "Add an Admin Comment",
            placeholder="Add an administrative note, decision, or instruction…",
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
            user_role="admin",
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
# User Management
# ---------------------------------------------------------------------------

def render_users() -> None:
    render_page_title("👥 User Management", "Create and manage platform users.")

    tab_list, tab_create, tab_skills = st.tabs(["📋 All Users", "➕ Create User", "🔧 Technician Skills"])

    with tab_list:
        _render_user_list()

    with tab_create:
        _render_create_user_form()

    with tab_skills:
        _render_skills_manager()


def _render_user_list() -> None:
    col1, col2 = st.columns([1, 3])
    with col1:
        role_filter = st.selectbox(
            "Filter by Role",
            options=["All", "requester", "technician", "admin"],
            key="user_role_filter",
        )
    with col2:
        show_inactive = st.checkbox("Include inactive users", key="show_inactive", value=False)

    with st.spinner("Loading users…"):
        users = admin_list_users(
            role=role_filter if role_filter != "All" else None,
            active_only=not show_inactive,
        )

    st.caption(f"**{len(users)}** user(s) found")
    render_users_table(users)

    if not users:
        return

    st.divider()
    st.markdown("#### Manage User")

    user_options = {
        f"[{u['role'].upper()}] {u['full_name']} ({u['username']})": u["id"]
        for u in users
    }
    selected_label = st.selectbox(
        "Select user to manage:",
        options=list(user_options.keys()),
        index=None,
        placeholder="Choose a user…",
        key="manage_user_select",
    )

    if selected_label:
        selected_user = next((u for u in users if u["id"] == user_options[selected_label]), None)
        if selected_user:
            _render_user_management_actions(selected_user)


def _render_user_management_actions(target_user: dict) -> None:
    user = get_current_user()
    st.markdown(
        f"Managing: **{target_user['full_name']}** "
        f"(`{target_user['username']}`) — {target_user['role'].title()}"
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        is_active = target_user["is_active"]
        action_label = "❌ Deactivate" if is_active else "✅ Activate"
        if st.button(action_label, key=f"toggle_{target_user['id']}", use_container_width=True):
            result = admin_toggle_user_active(target_user["id"], not is_active, actor_id=user["id"])
            if result["success"]:
                action_word = "deactivated" if is_active else "activated"
                show_success(f"User {action_word} successfully.")
                st.rerun()
            else:
                show_error(result["error"])

    with col2:
        if st.button("🔑 Reset Password", key=f"reset_pw_{target_user['id']}", use_container_width=True):
            st.session_state[f"show_reset_{target_user['id']}"] = True

    if st.session_state.get(f"show_reset_{target_user['id']}"):
        with st.form(f"reset_pw_form_{target_user['id']}", clear_on_submit=True):
            new_pw = st.text_input("New Password", type="password")
            confirm_pw = st.text_input("Confirm Password", type="password")
            submitted = st.form_submit_button("Set New Password", type="primary")
        if submitted:
            result = admin_do_reset_password(
                target_user["id"], new_pw, confirm_pw, actor_id=user["id"]
            )
            if result["success"]:
                show_success("Password reset successfully.")
                st.session_state.pop(f"show_reset_{target_user['id']}", None)
            else:
                show_error(result["error"])


def _render_create_user_form() -> None:
    st.markdown("#### Create New User")
    st.caption("You can create users with any role including Technician and Admin.")

    with st.form("create_user_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            full_name = st.text_input("Full Name *")
            username = st.text_input("Username *")
            email = st.text_input("Email *")
            department = st.text_input("Department")
        with col2:
            role = st.selectbox(
                "Role *",
                options=["requester", "technician", "admin"],
                format_func=lambda r: r.title(),
            )
            phone = st.text_input("Phone")
            password = st.text_input("Password *", type="password",
                                     help="Min 8 chars, upper, lower, digit, special.")
            confirm_password = st.text_input("Confirm Password *", type="password")

        submitted = st.form_submit_button("➕ Create User", type="primary", use_container_width=True)

    if submitted:
        user = get_current_user()
        result = admin_create_user(
            username=username,
            email=email,
            full_name=full_name,
            plain_password=password,
            role=role,
            department=department or None,
            phone=phone or None,
            actor_id=user["id"],
        )
        if result["success"]:
            show_success(f"User '{username}' created successfully with role '{role.title()}'.")
        else:
            for err in result["errors"]:
                show_error(err)


def _render_skills_manager() -> None:
    """Manage technician skills."""
    st.markdown("#### 🔧 Technician Skills Manager")
    st.caption("View and manage skill categories for each technician.")

    technicians = admin_list_technicians()
    if not technicians:
        show_info("No active technicians. Create technician accounts first.")
        return

    tech_options = {t["full_name"]: t["id"] for t in technicians}
    selected_tech = st.selectbox(
        "Select Technician",
        options=list(tech_options.keys()),
        index=None,
        placeholder="Choose a technician…",
        key="skills_tech_select",
    )

    if not selected_tech:
        return

    tech_id = tech_options[selected_tech]

    with get_db() as session:
        skills = get_skills_for_technician(session, tech_id)

    st.markdown(f"**Current Skills for {selected_tech}:**")
    if skills:
        for s in skills:
            col_s, col_r = st.columns([3, 1])
            with col_s:
                st.markdown(f"- {s.skill_category.value.replace('_', ' ').title()}"
                            + (f" — {s.notes}" if s.notes else ""))
            with col_r:
                if st.button("🗑️", key=f"rm_skill_{s.id}", help="Remove this skill"):
                    with get_db() as session:
                        remove_skill(session, tech_id, s.skill_category)
                    show_success(f"Removed skill '{s.skill_category.value}'")
                    st.rerun()
    else:
        st.caption("No skills assigned yet.")

    st.divider()

    # Add new skill
    available_skills = [s for s in SkillCategory if s not in {sk.skill_category for sk in skills}]
    if available_skills:
        with st.form(f"add_skill_form_{tech_id}"):
            new_skill = st.selectbox(
                "Add Skill",
                options=available_skills,
                format_func=lambda s: s.value.replace("_", " ").title(),
                index=0,
            )
            skill_notes = st.text_input("Notes (optional)", placeholder="e.g. 'Certified — 240V only'")
            submitted = st.form_submit_button("➕ Add Skill", type="primary")

        if submitted:
            with get_db() as session:
                try:
                    add_skill(session, tech_id, new_skill, skill_notes or None)
                    show_success(f"Added skill '{new_skill.value}' to {selected_tech}.")
                    st.rerun()
                except ValueError as exc:
                    show_error(str(exc))
    else:
        show_info("All available skills are already assigned to this technician.")


# ---------------------------------------------------------------------------
# Location Management
# ---------------------------------------------------------------------------

def render_locations() -> None:
    render_page_title("📍 Location Management", "Manage buildings, floors, and areas.")

    tab_list, tab_create = st.tabs(["📋 All Locations", "➕ Create Location"])

    with tab_list:
        _render_location_list()

    with tab_create:
        _render_create_location_form()


def _render_location_list() -> None:
    show_inactive = st.checkbox("Include inactive locations", key="loc_show_inactive", value=False)

    with get_db() as session:
        locations = get_all_locations(session, active_only=not show_inactive)

    st.caption(f"**{len(locations)}** location(s) found")

    if not locations:
        show_info("No locations yet. Create one in the 'Create Location' tab.")
        return

    # Display as table
    import pandas as pd
    rows = [
        {
            "ID": l.id,
            "Building": l.building_name,
            "Floor": l.floor or "—",
            "Area": l.area or "—",
            "Active": "✅" if l.is_active else "❌",
            "Display Name": l.display_name(),
        }
        for l in locations
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("#### Manage Location")

    loc_options = {f"{l.display_name()} (ID:{l.id})": l for l in locations}
    selected_label = st.selectbox(
        "Select location to manage:",
        options=list(loc_options.keys()),
        index=None,
        placeholder="Choose a location…",
        key="manage_loc_select",
    )

    if selected_label:
        loc = loc_options[selected_label]
        _render_location_management_actions(loc)


def _render_location_management_actions(loc) -> None:
    st.markdown(f"Managing: **{loc.display_name()}** (ID: {loc.id})")

    with st.form(f"loc_edit_form_{loc.id}"):
        col1, col2 = st.columns(2)
        with col1:
            building = st.text_input("Building Name *", value=loc.building_name)
            floor = st.text_input("Floor", value=loc.floor or "")
        with col2:
            area = st.text_input("Area", value=loc.area or "")
            description = st.text_input("Description", value=loc.description or "")

        save = st.form_submit_button("💾 Save Changes", type="primary")

    if save:
        with get_db() as session:
            try:
                update_location(
                    session, loc.id,
                    building_name=building,
                    floor=floor or None,
                    area=area or None,
                    description=description or None,
                )
                show_success("Location updated successfully.")
                st.rerun()
            except ValueError as exc:
                show_error(str(exc))

    st.divider()
    is_active = bool(loc.is_active)
    action_label = "❌ Deactivate" if is_active else "✅ Activate"
    if st.button(action_label, key=f"loc_toggle_{loc.id}", use_container_width=True):
        with get_db() as session:
            set_location_active(session, loc.id, not is_active)
        action_word = "deactivated" if is_active else "activated"
        show_success(f"Location {action_word} successfully.")
        st.rerun()


def _render_create_location_form() -> None:
    st.markdown("#### Create New Location")

    with st.form("create_location_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            building_name = st.text_input("Building Name *", placeholder="e.g. Main Headquarters")
            area = st.text_input("Area", placeholder="e.g. Reception (optional)")
        with col2:
            floor = st.text_input("Floor", placeholder="e.g. 3 (optional)")
            description = st.text_input("Description", placeholder="e.g. Access via North entrance (optional)")

        submitted = st.form_submit_button("➕ Create Location", type="primary", use_container_width=True)

    if submitted:
        if not building_name.strip():
            show_error("Building name is required.")
            return
        with get_db() as session:
            try:
                create_location(
                    session,
                    building_name=building_name,
                    floor=floor or None,
                    area=area or None,
                    description=description or None,
                )
                show_success(f"Location '{building_name}' created successfully.")
                st.rerun()
            except ValueError as exc:
                show_error(str(exc))


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def render_analytics() -> None:
    render_page_title("📈 Operational Analytics", "Detailed metrics and trend analysis with interactive filters.")

    # --- Filters ---
    with st.expander("🔍 Filters", expanded=True):
        col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)
        with col_f1:
            period = st.selectbox(
                "Date Range",
                options=[7, 14, 30, 60, 90, None],
                format_func=lambda d: f"Last {d} days" if d else "All time",
                index=2,
                key="analytics_period",
            )
        with col_f2:
            cat_opts = ["All"] + [c.value for c in RequestCategory]
            cat_filter = st.selectbox(
                "Category", cat_opts, key="analytics_cat",
                format_func=lambda c: c if c == "All" else CATEGORY_LABELS.get(RequestCategory(c), c.title()),
            )
        with col_f3:
            status_opts = ["All"] + [s.value for s in RequestStatus]
            status_filter = st.selectbox(
                "Status", status_opts, key="analytics_status",
                format_func=lambda s: s if s == "All" else STATUS_LABELS.get(RequestStatus(s), s.title()),
            )
        with col_f4:
            loc_opts = ["All"]
            full_df_for_locs = get_requests_dataframe()
            if not full_df_for_locs.empty and "location" in full_df_for_locs.columns:
                unique_locs = sorted(full_df_for_locs["location"].dropna().unique().tolist())[:20]
                loc_opts += unique_locs
            loc_filter = st.selectbox(
                "Location", loc_opts, key="analytics_loc",
            )
        with col_f5:
            if st.button("🔄 Refresh", key="analytics_refresh"):
                st.rerun()

    with st.spinner("Computing analytics…"):
        full_df = get_requests_dataframe()

        # Apply filters to the DataFrame
        filtered_df = full_df.copy()
        if period is not None and not filtered_df.empty and "created_at" in filtered_df.columns:
            cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=period)
            filtered_df = filtered_df[filtered_df["created_at"] >= cutoff]
        if cat_filter != "All" and not filtered_df.empty and "category" in filtered_df.columns:
            filtered_df = filtered_df[filtered_df["category"] == cat_filter]
        if status_filter != "All" and not filtered_df.empty and "status" in filtered_df.columns:
            filtered_df = filtered_df[filtered_df["status"] == status_filter]
        if loc_filter != "All" and not filtered_df.empty and "location" in filtered_df.columns:
            filtered_df = filtered_df[filtered_df["location"] == loc_filter]

        resolution_stats = get_resolution_time_stats(days=period)
        workload = get_technician_workload()
        daily_df = get_requests_over_time(days=period if period else 30)

    # --- Empty state ---
    if full_df.empty:
        render_empty_state("📭", "No requests in the system. "
                           "Submit requests to see analytics, charts, and trends here.")
        return

    if filtered_df.empty:
        render_empty_state("🔍", "No requests match the current filters. "
                           "Try adjusting the date range, category, status, or location.")
        return

    # --- Resolution KPIs ---
    avg = resolution_stats.get("avg_hours")
    med = resolution_stats.get("median_hours")
    render_kpi_row([
        {"label": "Avg Resolution Time",
         "value": f"{avg:.1f} hrs" if avg else "N/A",
         "help": f"Based on {resolution_stats.get('count', 0)} resolved requests"},
        {"label": "Median Resolution Time",
         "value": f"{med:.1f} hrs" if med else "N/A"},
        {"label": "Fastest Resolution",
         "value": f"{resolution_stats.get('min_hours', 0):.1f} hrs"
         if resolution_stats.get("min_hours") is not None else "N/A"},
        {"label": "Slowest Resolution",
         "value": f"{resolution_stats.get('max_hours', 0):.1f} hrs"
         if resolution_stats.get("max_hours") is not None else "N/A"},
    ])

    st.divider()

    # --- Chart 1: Requests created over time ---
    render_section_header("Request Volume Over Time")
    st.plotly_chart(
        requests_over_time_chart(daily_df, days=period if period else 30),
        use_container_width=True,
    )

    # --- Chart 2 + 3: Category + Status ---
    render_section_header("Distribution by Category & Status")
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(
            category_bar_chart(get_category_breakdown()),
            use_container_width=True,
        )
    with col2:
        st.plotly_chart(
            status_donut_chart(get_status_distribution()),
            use_container_width=True,
        )

    # --- Chart 4 + 5: Priority + Technician workload ---
    render_section_header("Priority Distribution & Technician Workload")
    col3, col4 = st.columns(2)
    with col3:
        st.plotly_chart(
            priority_bar_chart(get_priority_breakdown()),
            use_container_width=True,
        )
    with col4:
        st.plotly_chart(
            technician_workload_chart(workload),
            use_container_width=True,
        )

    # --- Chart 6 + 7: Location + Resolution trend ---
    render_section_header("Location Breakdown & Resolution Trends")
    col5, col6 = st.columns(2)
    with col5:
        st.plotly_chart(
            location_bar_chart(get_location_breakdown(filtered_df)),
            use_container_width=True,
        )
    with col6:
        st.plotly_chart(
            resolution_trend_chart(filtered_df),
            use_container_width=True,
        )

    # --- Resolution histogram + heatmap ---
    render_section_header("Resolution Analysis")
    col7, col8 = st.columns(2)
    with col7:
        st.plotly_chart(
            resolution_time_histogram(filtered_df),
            use_container_width=True,
        )
    with col8:
        st.plotly_chart(
            priority_status_heatmap(filtered_df),
            use_container_width=True,
        )

    # --- Technician workload table ---
    st.divider()
    render_section_header("Technician Workload Detail")
    render_technician_workload_table(workload)


# ---------------------------------------------------------------------------
# AI Reports
# ---------------------------------------------------------------------------

def render_ai_reports() -> None:
    render_page_title(
        "🤖 AI Management Reports",
        "Generate a narrative operations summary powered by AI.",
    )

    if not settings.ai_enabled:
        show_warning(
            "AI features are currently disabled. "
            "Set `GROQ_API_KEY` and `ENABLE_AI_FEATURES=true` in your `.env` file "
            "to enable AI report generation."
        )
        return

    col1, col2 = st.columns([1, 3])
    with col1:
        period = st.selectbox(
            "Reporting Period",
            options=[7, 14, 30, 60, 90, None],
            format_func=lambda d: f"Last {d} days" if d else "All time",
            index=2,
            key="report_period",
        )

    st.caption(
        "The AI reads live operational metrics and generates a professional "
        "management summary. This may take 10-20 seconds."
    )

    if st.button("📄 Generate Report", type="primary", key="generate_report"):
        with st.spinner("Gathering metrics and generating AI report…"):
            metrics = get_report_metrics(days=period)
            result = generate_operations_report(metrics)

        if result.succeeded:
            st.divider()
            st.markdown("### 📊 Generated Report")
            st.markdown(result.report_markdown)

            # Download button
            st.download_button(
                label="⬇️ Download Report (Markdown)",
                data=result.report_markdown,
                file_name=f"facilityops_report_{period or 'all'}_days.md",
                mime="text/markdown",
                key="download_report",
            )
        else:
            show_error(
                f"Report generation failed: {result.error}. "
                "Check your Groq API key and try again."
            )

    # Show the raw metrics that were fed into the report
    with st.expander("📊 View Raw Metrics Used", expanded=False):
        with st.spinner("Loading metrics…"):
            metrics = get_report_metrics(days=period)
        st.json(metrics)


# ---------------------------------------------------------------------------
# Admin Profile
# ---------------------------------------------------------------------------

def render_profile() -> None:
    user = get_current_user()
    render_page_title("👤 My Profile", "Manage your administrator account.")

    tab_info, tab_password = st.tabs(["📋 Profile Information", "🔑 Change Password"])

    with tab_info:
        with st.form("admin_profile_form"):
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
        with st.form("admin_password_form", clear_on_submit=True):
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
