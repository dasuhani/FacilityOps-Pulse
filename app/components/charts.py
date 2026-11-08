"""
app/components/charts.py
-------------------------
Reusable Plotly chart components for the analytics dashboard.

Each function accepts pre-computed data (dicts or DataFrames from
analytics_service.py) and returns a Plotly figure object.
The caller renders it with st.plotly_chart(fig, use_container_width=True).
"""

from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Colour palettes aligned with layout.py
# ---------------------------------------------------------------------------

STATUS_COLOUR_MAP = {
    "submitted": "#6366f1",
    "open": "#6b7280",
    "assigned": "#2563eb",
    "in_progress": "#0891b2",
    "on_hold": "#d97706",
    "resolved": "#16a34a",
    "closed": "#374151",
    "cancelled": "#dc2626",
}

PRIORITY_COLOUR_MAP = {
    "low": "#16a34a",
    "medium": "#d97706",
    "high": "#ea580c",
    "critical": "#dc2626",
}

CATEGORY_COLOUR_MAP = {
    "electrical": "#f59e0b",
    "plumbing": "#0ea5e9",
    "hvac": "#06b6d4",
    "cleaning": "#84cc16",
    "safety": "#ef4444",
    "equipment_maintenance": "#8b5cf6",
    "it_support": "#3b82f6",
    "network_wifi": "#6366f1",
    "computer_display": "#a855f7",
    "other": "#6b7280",
    # Legacy fallbacks
    "facility": "#7c3aed",
    "it": "#2563eb",
    "housekeeping": "#059669",
}

_CHART_TEMPLATE = "plotly_dark"
_CHART_HEIGHT = 360
_CHART_MARGIN = dict(l=20, r=20, t=40, b=20)


# ---------------------------------------------------------------------------
# Status distribution — donut chart
# ---------------------------------------------------------------------------

def status_donut_chart(status_counts: dict[str, int]) -> go.Figure:
    """Donut chart of request status distribution."""
    if not status_counts:
        return _empty_figure("No status data")

    labels = [k.replace("_", " ").title() for k in status_counts.keys()]
    values = list(status_counts.values())
    colours = [STATUS_COLOUR_MAP.get(k, "#9ca3af") for k in status_counts.keys()]

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.52,
            marker=dict(colors=colours),
            textinfo="label+percent",
            hovertemplate="%{label}: %{value} requests<extra></extra>",
        )
    )
    fig.update_layout(
        title_text="Requests by Status",
        template=_CHART_TEMPLATE,
        height=_CHART_HEIGHT,
        margin=_CHART_MARGIN,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.2),
    )
    return fig


# ---------------------------------------------------------------------------
# Priority distribution — horizontal bar chart
# ---------------------------------------------------------------------------

def priority_bar_chart(priority_counts: dict[str, int]) -> go.Figure:
    """Horizontal bar chart of request priority distribution."""
    if not priority_counts:
        return _empty_figure("No priority data")

    order = ["critical", "high", "medium", "low"]
    priorities = [p for p in order if p in priority_counts]
    counts = [priority_counts[p] for p in priorities]
    colours = [PRIORITY_COLOUR_MAP.get(p, "#9ca3af") for p in priorities]
    labels = [p.title() for p in priorities]

    fig = go.Figure(
        go.Bar(
            x=counts,
            y=labels,
            orientation="h",
            marker_color=colours,
            text=counts,
            textposition="outside",
            hovertemplate="%{y}: %{x} requests<extra></extra>",
        )
    )
    fig.update_layout(
        title_text="Requests by Priority",
        template=_CHART_TEMPLATE,
        height=_CHART_HEIGHT,
        margin=_CHART_MARGIN,
        xaxis_title="Number of Requests",
        yaxis_title=None,
    )
    return fig


# ---------------------------------------------------------------------------
# Category breakdown — vertical bar chart
# ---------------------------------------------------------------------------

def category_bar_chart(category_counts: dict[str, int]) -> go.Figure:
    """Vertical bar chart of request categories."""
    if not category_counts:
        return _empty_figure("No category data")

    sorted_items = sorted(category_counts.items(), key=lambda x: -x[1])
    categories = [k.title() for k, _ in sorted_items]
    counts = [v for _, v in sorted_items]
    colours = [
        CATEGORY_COLOUR_MAP.get(k.lower(), "#9ca3af")
        for k, _ in sorted_items
    ]

    fig = go.Figure(
        go.Bar(
            x=categories,
            y=counts,
            marker_color=colours,
            text=counts,
            textposition="outside",
            hovertemplate="%{x}: %{y} requests<extra></extra>",
        )
    )
    fig.update_layout(
        title_text="Requests by Category",
        template=_CHART_TEMPLATE,
        height=_CHART_HEIGHT,
        margin=_CHART_MARGIN,
        xaxis_title=None,
        yaxis_title="Number of Requests",
    )
    return fig


# ---------------------------------------------------------------------------
# Request volume over time — line chart
# ---------------------------------------------------------------------------

def requests_over_time_chart(
    daily_df: pd.DataFrame,
    days: int = 30,
) -> go.Figure:
    """Line chart of daily request submissions."""
    if daily_df is None or daily_df.empty:
        return _empty_figure("No volume data")

    fig = go.Figure(
        go.Scatter(
            x=daily_df["date"],
            y=daily_df["count"],
            mode="lines+markers",
            line=dict(color="#2563eb", width=2),
            marker=dict(size=5),
            fill="tozeroy",
            fillcolor="rgba(37, 99, 235, 0.1)",
            hovertemplate="%{x|%d %b}: %{y} requests<extra></extra>",
        )
    )
    fig.update_layout(
        title_text=f"Daily Request Volume — Last {days} Days",
        template=_CHART_TEMPLATE,
        height=_CHART_HEIGHT,
        margin=_CHART_MARGIN,
        xaxis_title=None,
        yaxis_title="Requests",
    )
    return fig


# ---------------------------------------------------------------------------
# Technician workload — grouped bar chart
# ---------------------------------------------------------------------------

def technician_workload_chart(workload: list[dict]) -> go.Figure:
    """Grouped bar chart comparing total assigned vs currently open per technician."""
    if not workload:
        return _empty_figure("No technician data")

    names = [t["name"] for t in workload]
    assigned = [t["assigned_total"] for t in workload]
    open_counts = [t["open_count"] for t in workload]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Total Assigned",
            x=names,
            y=assigned,
            marker_color="#2563eb",
            hovertemplate="%{x}<br>Total assigned: %{y}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Currently Open",
            x=names,
            y=open_counts,
            marker_color="#d97706",
            hovertemplate="%{x}<br>Open: %{y}<extra></extra>",
        )
    )
    fig.update_layout(
        title_text="Technician Workload",
        barmode="group",
        template=_CHART_TEMPLATE,
        height=_CHART_HEIGHT,
        margin=_CHART_MARGIN,
        xaxis_title=None,
        yaxis_title="Requests",
        legend=dict(orientation="h", yanchor="bottom", y=-0.3),
    )
    return fig


# ---------------------------------------------------------------------------
# Resolution time histogram
# ---------------------------------------------------------------------------

def resolution_time_histogram(df: pd.DataFrame) -> go.Figure:
    """Histogram of resolution times in hours."""
    if df is None or df.empty:
        return _empty_figure("No resolved requests data")

    resolved = df[df["status"].isin(["resolved", "closed"])].copy()
    resolved = resolved.dropna(subset=["resolved_at", "created_at"])

    if resolved.empty:
        return _empty_figure("No resolved requests in this period")

    resolved["resolution_hours"] = (
        (resolved["resolved_at"] - resolved["created_at"]).dt.total_seconds() / 3600
    )
    resolved = resolved[resolved["resolution_hours"] >= 0]

    fig = px.histogram(
        resolved,
        x="resolution_hours",
        nbins=20,
        title="Resolution Time Distribution",
        labels={"resolution_hours": "Hours to Resolve"},
        color_discrete_sequence=["#16a34a"],
        template=_CHART_TEMPLATE,
    )
    fig.update_layout(
        height=_CHART_HEIGHT,
        margin=_CHART_MARGIN,
        yaxis_title="Number of Requests",
    )
    return fig


# ---------------------------------------------------------------------------
# Priority vs Status heatmap
# ---------------------------------------------------------------------------

def priority_status_heatmap(df: pd.DataFrame) -> go.Figure:
    """Heatmap showing count of requests for each (priority, status) combination."""
    if df is None or df.empty:
        return _empty_figure("No data for heatmap")

    pivot = (
        df.groupby(["priority", "status"])
        .size()
        .unstack(fill_value=0)
    )

    priority_order = ["critical", "high", "medium", "low"]
    pivot = pivot.reindex(
        [p for p in priority_order if p in pivot.index]
    )

    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=[c.replace("_", " ").title() for c in pivot.columns],
            y=[r.title() for r in pivot.index],
            colorscale="Blues",
            text=pivot.values,
            texttemplate="%{text}",
            hovertemplate="Priority: %{y}<br>Status: %{x}<br>Count: %{z}<extra></extra>",
        )
    )
    fig.update_layout(
        title_text="Priority × Status Distribution",
        template=_CHART_TEMPLATE,
        height=_CHART_HEIGHT,
        margin=_CHART_MARGIN,
        xaxis_title="Status",
        yaxis_title="Priority",
    )
    return fig


# ---------------------------------------------------------------------------
# Requests by location — horizontal bar chart
# ---------------------------------------------------------------------------

def location_bar_chart(location_counts: dict[str, int], top_n: int = 10) -> go.Figure:
    """Horizontal bar chart of requests by location (top N)."""
    if not location_counts:
        return _empty_figure("No location data")

    sorted_items = sorted(location_counts.items(), key=lambda x: -x[1])[:top_n]
    locations = [k for k, _ in sorted_items]
    counts = [v for _, v in sorted_items]

    fig = go.Figure(
        go.Bar(
            x=counts,
            y=locations,
            orientation="h",
            marker_color="#6366f1",
            text=counts,
            textposition="outside",
            hovertemplate="%{y}: %{x} requests<extra></extra>",
        )
    )
    fig.update_layout(
        title_text="Requests by Location",
        template=_CHART_TEMPLATE,
        height=_CHART_HEIGHT,
        margin=_CHART_MARGIN,
        xaxis_title="Number of Requests",
        yaxis_title=None,
        yaxis=dict(autorange="reversed"),
    )
    return fig


# ---------------------------------------------------------------------------
# Resolution time trend — line chart
# ---------------------------------------------------------------------------

def resolution_trend_chart(df: pd.DataFrame) -> go.Figure:
    """
    Line chart showing average resolution time over time (by week).
    Uses the full requests DataFrame from analytics_service.
    """
    if df is None or df.empty:
        return _empty_figure("No resolution data")

    resolved = df[df["status"].isin(["resolved", "closed"])].copy()
    resolved = resolved.dropna(subset=["resolved_at", "created_at"])

    if resolved.empty:
        return _empty_figure("No resolved requests to trend")

    resolved["resolution_hours"] = (
        (resolved["resolved_at"] - resolved["created_at"]).dt.total_seconds() / 3600
    )
    resolved = resolved[resolved["resolution_hours"] >= 0]

    if resolved.empty:
        return _empty_figure("No valid resolution times")

    # Group by week
    resolved["week"] = resolved["resolved_at"].dt.to_period("W").dt.start_time
    weekly = resolved.groupby("week")["resolution_hours"].agg(["mean", "count"]).reset_index()
    weekly.columns = ["week", "avg_hours", "count"]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=weekly["week"],
            y=weekly["avg_hours"].round(1),
            mode="lines+markers",
            line=dict(color="#16a34a", width=2),
            marker=dict(size=6),
            hovertemplate="%{x|%d %b %Y}: %{y} hrs avg<extra></extra>",
            name="Avg Resolution (hrs)",
        )
    )
    # Add count as secondary marker size info
    fig.update_layout(
        title_text="Resolution Time Trend (Weekly Average)",
        template=_CHART_TEMPLATE,
        height=_CHART_HEIGHT,
        margin=_CHART_MARGIN,
        xaxis_title=None,
        yaxis_title="Hours to Resolve",
    )
    return fig


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _empty_figure(message: str) -> go.Figure:
    """Return a blank figure with a centred 'no data' annotation."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=14, color="#9ca3af"),
    )
    fig.update_layout(
        template=_CHART_TEMPLATE,
        height=_CHART_HEIGHT,
        margin=_CHART_MARGIN,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig
