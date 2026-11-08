"""
app/components/tables.py
-------------------------
Reusable Streamlit data table components for displaying request lists,
user lists, status history, and assignment details.

All table functions accept plain Python lists/dicts (never ORM objects)
and use st.dataframe / st.markdown for rendering.
"""

from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import streamlit as st

from app.components.layout import status_badge, priority_badge


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_dt(iso_str: Optional[str]) -> str:
    """Format an ISO datetime string to a readable local string."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%d %b %Y  %H:%M")
    except (ValueError, TypeError):
        return str(iso_str)


def _truncate(text: Optional[str], max_len: int = 60) -> str:
    if not text:
        return "—"
    text = str(text)
    return text[:max_len] + "…" if len(text) > max_len else text


# ---------------------------------------------------------------------------
# Request tables
# ---------------------------------------------------------------------------

def render_requests_table(
    requests: list[dict],
    show_requester: bool = False,
    show_technician: bool = False,
    selectable: bool = False,
    key: str = "requests_table",
) -> Optional[dict]:
    """
    Render a filterable, styled requests table.

    Parameters
    ----------
    requests      : list of request dicts (from business layer)
    show_requester: include requester name column
    show_technician: include technician name column
    selectable    : if True, add a row selector and return the selected row dict
    key           : unique widget key for selectbox

    Returns
    -------
    The selected request dict if selectable=True and a row is selected,
    otherwise None.
    """
    if not requests:
        st.info("No requests to display.")
        return None

    rows = []
    for r in requests:
        row = {
            "Ref #": r.get("reference_number", "—"),
            "Title": _truncate(r.get("title"), 55),
            "Category": r.get("category", "—").replace("_", " ").title(),
            "Priority": r.get("priority", "—").title(),
            "Status": r.get("status", "—").replace("_", " ").title(),
            "Location": _truncate(r.get("location"), 30),
            "Submitted": _fmt_dt(r.get("created_at")),
        }
        if show_requester:
            row["Requester"] = r.get("requester_name", "—")
        if show_technician:
            row["Technician"] = r.get("technician_name", "Unassigned")
        row["_id"] = r.get("id")
        rows.append(row)

    df = pd.DataFrame(rows)

    # Colour-code Priority and Status columns via a styler
    def _colour_priority(val: str) -> str:
        colours = {
            "Critical": "color: #dc2626; font-weight: bold;",
            "High": "color: #ea580c; font-weight: bold;",
            "Medium": "color: #d97706;",
            "Low": "color: #16a34a;",
        }
        return colours.get(val, "")

    def _colour_status(val: str) -> str:
        colours = {
            "Open": "color: #6b7280;",
            "In Progress": "color: #2563eb; font-weight: bold;",
            "On Hold": "color: #d97706;",
            "Resolved": "color: #16a34a;",
            "Closed": "color: #374151;",
            "Cancelled": "color: #dc2626;",
        }
        return colours.get(val, "")

    display_cols = [c for c in df.columns if c != "_id"]
    styled = (
        df[display_cols]
        .style
        .applymap(_colour_priority, subset=["Priority"])
        .applymap(_colour_status, subset=["Status"])
    )

    st.dataframe(styled, use_container_width=True, hide_index=True)

    if not selectable:
        return None

    # Selectbox for choosing a request to act on
    options = {f"{r['Ref #']} — {r['Title']}": r["_id"] for r in rows}
    if not options:
        return None

    selected_label = st.selectbox(
        "Select a request to view details:",
        options=list(options.keys()),
        key=key,
        index=None,
        placeholder="Choose a request…",
    )
    if selected_label:
        selected_id = options[selected_label]
        return next((r for r in requests if r.get("id") == selected_id), None)
    return None


def render_request_detail_card(request: dict) -> None:
    """
    Render a full detail card for a single request including all fields,
    AI suggestions, and assignment info.
    """
    st.markdown(
        f"### {request.get('reference_number', '')} — {request.get('title', '')}"
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f"**Status:** {request.get('status', '').replace('_', ' ').title()}"
        )
        st.markdown(f"**Category:** {request.get('category', '').title()}")
        st.markdown(
            f"**Sub-category:** {request.get('sub_category') or '—'}"
        )
    with col2:
        st.markdown(f"**Priority:** {request.get('priority', '').title()}")
        st.markdown(f"**Location:** {request.get('location', '—')}")
        st.markdown(f"**Building:** {request.get('building') or '—'}")
    with col3:
        st.markdown(
            f"**Submitted:** {_fmt_dt(request.get('created_at'))}"
        )
        st.markdown(f"**Requester:** {request.get('requester_name', '—')}")
        st.markdown(
            f"**Technician:** {request.get('technician_name') or 'Unassigned'}"
        )

    st.divider()
    st.markdown("**Description:**")
    st.markdown(
        f"<div class='info-panel'>{request.get('description', '—')}</div>",
        unsafe_allow_html=True,
    )

    # AI suggestions
    if request.get("ai_suggested_category") or request.get("ai_suggested_priority"):
        with st.expander("🤖 AI Analysis", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(
                    f"**Suggested Category:** {request.get('ai_suggested_category') or '—'}"
                )
                conf = request.get("ai_confidence_score")
                conf_str = f"{conf * 100:.0f}%" if conf else "—"
                st.markdown(f"**Confidence:** {conf_str}")
            with c2:
                st.markdown(
                    f"**Suggested Priority:** {request.get('ai_suggested_priority', '—').title()}"
                )
            notes = request.get("ai_classification_notes")
            if notes:
                st.caption(f"📝 {notes}")

    # Resolution notes
    if request.get("resolution_notes"):
        with st.expander("📋 Resolution Notes", expanded=True):
            st.markdown(request["resolution_notes"])


# ---------------------------------------------------------------------------
# Status history timeline
# ---------------------------------------------------------------------------

def render_status_history(history: list[dict]) -> None:
    """Render a vertical timeline of status history entries."""
    if not history:
        st.info("No status history available.")
        return

    st.markdown("#### 📅 Status History")

    for i, entry in enumerate(history):
        prev = entry.get("previous_status") or "Created"
        curr = entry.get("new_status", "").replace("_", " ").title()
        prev_fmt = prev.replace("_", " ").title()
        changed_at = _fmt_dt(entry.get("changed_at"))
        role = entry.get("changed_by_role", "system").title()
        note = entry.get("note")

        connector = "┌" if i == 0 else ("└" if i == len(history) - 1 else "├")

        st.markdown(
            f"**{connector} {changed_at}** &nbsp;&nbsp; "
            f"`{prev_fmt}` → `{curr}` &nbsp; *(by {role})*",
            unsafe_allow_html=True,
        )
        if note:
            st.caption(f"   💬 {note}")


# ---------------------------------------------------------------------------
# User management table (admin)
# ---------------------------------------------------------------------------

def render_users_table(users: list[dict]) -> None:
    """Render the admin user management table."""
    if not users:
        st.info("No users to display.")
        return

    rows = [
        {
            "ID": u.get("id"),
            "Username": u.get("username", "—"),
            "Full Name": u.get("full_name", "—"),
            "Email": u.get("email", "—"),
            "Role": u.get("role", "—").title(),
            "Department": u.get("department") or "—",
            "Active": "✅ Yes" if u.get("is_active") else "❌ No",
            "Last Login": _fmt_dt(u.get("last_login_at")),
            "Created": _fmt_dt(u.get("created_at")),
        }
        for u in users
    ]

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Duplicate / similar request warning
# ---------------------------------------------------------------------------

def render_similar_requests_warning(similar: list[dict]) -> None:
    """
    Display a warning box listing potentially duplicate requests.
    Called from the submission form before the user finalises a request.
    """
    if not similar:
        return

    st.warning(
        f"⚠️ **{len(similar)} similar request(s) found.** "
        "Please review before submitting to avoid duplicates."
    )

    rows = [
        {
            "Ref #": s["reference_number"],
            "Title": _truncate(s["title"], 50),
            "Status": s["status"].replace("_", " ").title(),
            "Similarity": s["similarity_pct"],
        }
        for s in similar
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Technician workload table
# ---------------------------------------------------------------------------

def render_technician_workload_table(workload: list[dict]) -> None:
    if not workload:
        st.info("No technician data available.")
        return

    rows = [
        {
            "Technician": t["name"],
            "Total Assigned": t["assigned_total"],
            "Currently Open": t["open_count"],
        }
        for t in workload
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# SLA breach table
# ---------------------------------------------------------------------------

def render_sla_breach_table(breach_df: pd.DataFrame) -> None:
    if breach_df is None or breach_df.empty:
        st.success("✅ No SLA breaches detected.")
        return

    display = breach_df[
        ["reference_number", "title", "priority", "status", "age_hours", "sla_hours", "technician_name"]
    ].copy()
    display.columns = ["Ref #", "Title", "Priority", "Status", "Age (hrs)", "SLA (hrs)", "Technician"]
    display["Age (hrs)"] = display["Age (hrs)"].round(1)
    display["Over SLA by"] = (display["Age (hrs)"] - display["SLA (hrs)"]).round(1).astype(str) + " hrs"
    display["Title"] = display["Title"].apply(lambda x: _truncate(str(x), 45))

    st.dataframe(display, use_container_width=True, hide_index=True)
