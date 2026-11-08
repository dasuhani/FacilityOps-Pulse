"""
business/analytics_service.py
-------------------------------
Data aggregation and analytics for the admin dashboard and AI report generator.

All functions return plain Python dicts or Pandas DataFrames —
never ORM objects — so the UI and report generator layers can consume
them without an active database session.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd

from database.connection import get_db
from database.crud.request_crud import (
    count_requests_by_status,
    count_requests_by_category,
    count_requests_by_priority,
    get_requests_dataframe_raw,
    get_all_requests,
)
from database.crud.assignment_crud import get_technician_open_workload
from database.crud.user_crud import get_technicians
from database.models.request import RequestStatus, RequestPriority

logger = logging.getLogger(__name__)

# SLA thresholds in hours per priority level
SLA_HOURS = {
    "critical": 4,
    "high": 8,
    "medium": 24,
    "low": 72,
}


# ---------------------------------------------------------------------------
# Core DataFrames
# ---------------------------------------------------------------------------

def get_requests_dataframe() -> pd.DataFrame:
    """
    Return all requests as a normalised Pandas DataFrame.
    Column names match the ServiceRequest fields plus joined technician_name.

    When the database has no requests, returns an empty DataFrame with the
    correct column schema so downstream functions can safely check column
    existence without KeyErrors.
    """
    # Canonical column schema produced by get_requests_dataframe_raw.
    # Listed here so that an empty result still has a consistent shape.
    _EXPECTED_COLUMNS = [
        "id", "reference_number", "title", "category", "priority",
        "status", "location", "created_at", "resolved_at", "requester_id",
        "technician_name",
    ]

    with get_db() as session:
        rows = get_requests_dataframe_raw(session)

    if not rows:
        return pd.DataFrame(columns=_EXPECTED_COLUMNS)

    df = pd.DataFrame(rows)

    # Convert enum objects to strings for downstream processing
    for col in ("category", "priority", "status"):
        if col in df.columns:
            df[col] = df[col].apply(lambda v: v.value if hasattr(v, "value") else str(v))

    # Parse timestamps
    for ts_col in ("created_at", "resolved_at"):
        if ts_col in df.columns:
            df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")

    return df


def _filter_by_period(df: pd.DataFrame, days: Optional[int]) -> pd.DataFrame:
    """Filter dataframe to the last N days. None means all time."""
    if days is None or df.empty or "created_at" not in df.columns:
        return df
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
    return df[df["created_at"] >= cutoff]


# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------

def get_summary_counts() -> dict:
    """Fast count queries for the top-level dashboard KPI cards."""
    with get_db() as session:
        by_status = count_requests_by_status(session)
        by_category = count_requests_by_category(session)
        by_priority = count_requests_by_priority(session)

    total = sum(by_status.values())

    return {
        "total": total,
        "open": by_status.get("open", 0),
        "in_progress": by_status.get("in_progress", 0),
        "on_hold": by_status.get("on_hold", 0),
        "resolved": by_status.get("resolved", 0),
        "closed": by_status.get("closed", 0),
        "cancelled": by_status.get("cancelled", 0),
        "by_category": by_category,
        "by_priority": by_priority,
        "critical": by_priority.get("critical", 0),
        "high": by_priority.get("high", 0),
    }


def get_resolution_time_stats(days: Optional[int] = 30) -> dict:
    """
    Compute resolution time statistics from requests with both
    created_at and resolved_at populated.

    Returns zeros/None when there are no resolved requests (including
    when the database is completely empty).
    """
    df = get_requests_dataframe()
    df = _filter_by_period(df, days)

    # Guard: empty DataFrame or missing required columns
    if df.empty or "status" not in df.columns:
        return {
            "avg_hours": None,
            "median_hours": None,
            "min_hours": None,
            "max_hours": None,
            "count": 0,
        }

    resolved = df[df["status"].isin(["resolved", "closed"])].copy()
    if "resolved_at" not in resolved.columns or "created_at" not in resolved.columns:
        return {
            "avg_hours": None,
            "median_hours": None,
            "min_hours": None,
            "max_hours": None,
            "count": 0,
        }

    resolved = resolved.dropna(subset=["resolved_at", "created_at"])

    if resolved.empty:
        return {
            "avg_hours": None,
            "median_hours": None,
            "min_hours": None,
            "max_hours": None,
            "count": 0,
        }

    resolved["resolution_hours"] = (
        (resolved["resolved_at"] - resolved["created_at"])
        .dt.total_seconds() / 3600
    )
    resolved = resolved[resolved["resolution_hours"] >= 0]

    return {
        "avg_hours": round(resolved["resolution_hours"].mean(), 2),
        "median_hours": round(resolved["resolution_hours"].median(), 2),
        "min_hours": round(resolved["resolution_hours"].min(), 2),
        "max_hours": round(resolved["resolution_hours"].max(), 2),
        "count": len(resolved),
    }


# ---------------------------------------------------------------------------
# Chart data (returns dicts that Plotly can consume directly)
# ---------------------------------------------------------------------------

def get_requests_over_time(days: int = 30) -> pd.DataFrame:
    """
    Return a DataFrame with daily request submission counts for a line chart.
    Columns: date (datetime), count (int).
    """
    df = get_requests_dataframe()
    df = _filter_by_period(df, days)

    if df.empty or "created_at" not in df.columns:
        return pd.DataFrame(columns=["date", "count"])

    df["date"] = df["created_at"].dt.date
    daily = df.groupby("date").size().reset_index(name="count")
    daily["date"] = pd.to_datetime(daily["date"])

    # Fill missing dates with 0
    date_range = pd.date_range(
        start=daily["date"].min(), end=daily["date"].max(), freq="D"
    )
    daily = daily.set_index("date").reindex(date_range, fill_value=0).reset_index()
    daily.columns = ["date", "count"]
    return daily


def get_status_distribution() -> dict[str, int]:
    """For a pie/donut chart of request statuses."""
    with get_db() as session:
        return count_requests_by_status(session)


def get_category_breakdown() -> dict[str, int]:
    """For a bar chart of request categories."""
    with get_db() as session:
        return count_requests_by_category(session)


def get_priority_breakdown() -> dict[str, int]:
    """For a bar/pie chart of request priorities."""
    with get_db() as session:
        return count_requests_by_priority(session)


def get_technician_workload() -> list[dict]:
    """
    Return per-technician workload stats for a bar chart.
    Each dict: {name, assigned_count, open_count}.
    """
    with get_db() as session:
        technicians = get_technicians(session, active_only=True)
        open_workload = get_technician_open_workload(session)

    df = get_requests_dataframe()

    result = []
    for tech in technicians:
        # Total assigned (all time)
        if not df.empty and "technician_name" in df.columns:
            assigned_total = len(df[df["technician_name"] == tech.full_name])
        else:
            assigned_total = 0

        # Currently open/in-progress
        open_count = open_workload.get(tech.id, 0)

        result.append({
            "name": tech.full_name,
            "technician_id": tech.id,
            "assigned_total": assigned_total,
            "open_count": open_count,
        })

    return sorted(result, key=lambda x: -x["open_count"])


# ---------------------------------------------------------------------------
# SLA breach detection
# ---------------------------------------------------------------------------

def get_sla_breach_count(df: Optional[pd.DataFrame] = None) -> int:
    """
    Count open/in-progress requests that have exceeded their SLA threshold.
    """
    if df is None:
        df = get_requests_dataframe()

    if df.empty:
        return 0

    active = df[df["status"].isin([
        "submitted", "open", "assigned", "in_progress", "on_hold",
    ])].copy()
    if active.empty:
        return 0

    now = pd.Timestamp.now(tz="UTC")
    active["age_hours"] = (now - active["created_at"]).dt.total_seconds() / 3600
    active["sla_hours"] = active["priority"].map(SLA_HOURS).fillna(24)

    return int((active["age_hours"] > active["sla_hours"]).sum())


def get_sla_breach_requests(df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Return full rows for requests that have breached SLA."""
    if df is None:
        df = get_requests_dataframe()

    if df.empty:
        return pd.DataFrame()

    active = df[df["status"].isin([
        "submitted", "open", "assigned", "in_progress", "on_hold",
    ])].copy()
    if active.empty:
        return pd.DataFrame()

    now = pd.Timestamp.now(tz="UTC")
    active["age_hours"] = (now - active["created_at"]).dt.total_seconds() / 3600
    active["sla_hours"] = active["priority"].map(SLA_HOURS).fillna(24)
    return active[active["age_hours"] > active["sla_hours"]].sort_values(
        "age_hours", ascending=False
    )


# ---------------------------------------------------------------------------
# Location breakdown
# ---------------------------------------------------------------------------

def get_location_breakdown(df: Optional[pd.DataFrame] = None) -> dict[str, int]:
    """
    Return {location: count} for request locations.
    Uses the building column if available, otherwise the location string.
    """
    if df is None:
        df = get_requests_dataframe()

    if df.empty or "location" not in df.columns:
        return {}

    # Use building if available, otherwise location
    loc_col = "building" if "building" in df.columns and df["building"].notna().any() else "location"
    counts = df[loc_col].fillna(df["location"] if "location" in df.columns else "Unknown").value_counts()

    return {str(k): int(v) for k, v in counts.items() if k and str(k) != "nan"}


# ---------------------------------------------------------------------------
# Overdue requests (past their due_date)
# ---------------------------------------------------------------------------

def get_overdue_count(df: Optional[pd.DataFrame] = None) -> int:
    """
    Count active requests that have a due_date which has already passed.
    Different from SLA breach — this uses the explicit due_date field.
    """
    if df is None:
        df = get_requests_dataframe()

    if df.empty or "due_date" not in df.columns:
        return 0

    # Check if due_date column exists in the raw dataframe
    # The raw dataframe from get_requests_dataframe_raw may not include due_date
    # Fall back to SLA breach count if due_date is not available
    active = df[df["status"].isin([
        "submitted", "open", "assigned", "in_progress", "on_hold",
    ])].copy()

    if active.empty:
        return 0

    # If we have due_date column, use it
    if "due_date" in active.columns and active["due_date"].notna().any():
        now = pd.Timestamp.now(tz="UTC")
        active["due_date"] = pd.to_datetime(active["due_date"], utc=True, errors="coerce")
        return int((active["due_date"].notna() & (active["due_date"] < now)).sum())

    # Fall back to SLA breach count
    return get_sla_breach_count(df)


# ---------------------------------------------------------------------------
# Recent requests (for dashboard "recently updated" sections)
# ---------------------------------------------------------------------------

def get_recent_requests_for_technician(
    technician_id: int, limit: int = 5
) -> list[dict]:
    """
    Return the most recently updated requests assigned to a technician.
    Uses the requests DataFrame sorted by updated_at.
    """
    from database.connection import get_db
    from database.crud.request_crud import get_requests_for_technician
    from database.models.request import RequestStatus

    with get_db() as session:
        reqs = get_requests_for_technician(
            session, technician_id=technician_id,
            status_filter=None,  # all statuses
        )
        if not reqs:
            return []

        # Sort by updated_at descending
        reqs_sorted = sorted(
            reqs, key=lambda r: r.updated_at or r.created_at, reverse=True
        )
        result = []
        for r in reqs_sorted[:limit]:
            d = r.to_dict()
            d["requester_name"] = r.requester.full_name if r.requester else "Unknown"
            result.append(d)
        return result


def get_recent_requests_for_requester(
    requester_id: int, limit: int = 5
) -> list[dict]:
    """
    Return the most recently updated requests submitted by a requester.
    """
    from database.connection import get_db
    from database.crud.request_crud import get_requests_for_requester

    with get_db() as session:
        reqs = get_requests_for_requester(
            session, requester_id=requester_id,
            status_filter=None, limit=limit,
        )
        if not reqs:
            return []

        result = []
        for r in reqs:
            d = r.to_dict()
            d["technician_name"] = (
                r.assigned_technician.full_name if r.assigned_technician else None
            )
            result.append(d)
        return result


# ---------------------------------------------------------------------------
# Report metrics (fed to report_generator.py)
# ---------------------------------------------------------------------------

def get_report_metrics(days: Optional[int] = 30) -> dict:
    """
    Assemble the full metrics dict consumed by the AI report generator.
    """
    summary = get_summary_counts()
    resolution = get_resolution_time_stats(days=days)

    df = get_requests_dataframe()
    df_period = _filter_by_period(df, days)

    sla_breach_count = get_sla_breach_count(df_period)
    unassigned_count = (
        int((df_period["technician_name"] == "None").sum())
        if not df_period.empty and "technician_name" in df_period.columns
        else 0
    )

    # Technician summary
    tech_workload = get_technician_workload()
    technician_summary = [
        {
            "name": t["name"],
            "assigned": t["assigned_total"],
            "resolved": 0,  # would need a join — approximated for now
        }
        for t in tech_workload
    ]

    period_label = f"Last {days} days" if days else "All time"

    return {
        "period_label": period_label,
        "total_requests": summary["total"],
        "open_count": summary["open"],
        "in_progress_count": summary["in_progress"],
        "resolved_count": summary["resolved"],
        "closed_count": summary["closed"],
        "cancelled_count": summary["cancelled"],
        "critical_count": summary["critical"],
        "high_count": summary["high"],
        "avg_resolution_hours": resolution["avg_hours"],
        "category_breakdown": summary["by_category"],
        "technician_summary": technician_summary,
        "sla_breach_count": sla_breach_count,
        "unassigned_count": unassigned_count,
    }
