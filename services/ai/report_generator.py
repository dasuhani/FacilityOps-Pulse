"""
services/ai/report_generator.py
---------------------------------
AI-generated management reports using the Groq LLM.

The report generator takes aggregated operational metrics (pre-calculated
in Python/SQL by analytics_service.get_report_metrics()) and asks the LLM
to produce a professional written summary.

IMPORTANT: All numerical statistics are calculated in Python BEFORE being
passed to the LLM.  The LLM never invents numbers or accesses the database.
It only narrates the data it is given.

Report sections:
  - Executive Summary
  - Key Performance Highlights
  - Areas of Concern (overdue requests, SLA breaches, recurring issues)
  - Technician Workload Distribution
  - Most Common Request Categories
  - Recurring Problem Locations
  - Suggested Operational Improvements
"""

import logging
from dataclasses import dataclass
from typing import Optional

from services.ai.groq_client import chat_completion
from core.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a professional Facility and IT Service Management analyst.
Your job is to generate a concise, professional management report based on
operational metrics provided to you.

CRITICAL: Every number in your report must come from the data provided
below.  Do NOT invent, estimate, or hallucinate any figures.  If data is
missing, state that clearly rather than guessing.

Report requirements:
1. Write in a formal but accessible tone suitable for management review.
2. Structure the report with these sections (use Markdown headings):
   - Executive Summary (2–3 sentences)
   - Key Performance Highlights (bullet points)
   - Areas of Concern (bullet points — only include if issues exist)
   - Technician Workload Distribution (brief paragraph)
   - Most Common Request Categories (bullet points)
   - Recurring Problem Locations (bullet points — only if data available)
   - Suggested Operational Improvements (3–5 actionable bullet points)
3. Base every observation strictly on the data provided.
4. If data is limited, note that in the summary and work with what is available.
5. Keep the total report under 800 words.
6. Output Markdown only — no preamble, no explanation outside the report.
"""


@dataclass
class ReportResult:
    report_markdown: str
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


def generate_operations_report(metrics: dict) -> ReportResult:
    """
    Generate a Markdown management report from operational metrics.

    Parameters
    ----------
    metrics : dict
        Aggregated stats dict from analytics_service.get_report_metrics().
        All numbers must be pre-calculated — the LLM only narrates them.

    Returns
    -------
    ReportResult
        .report_markdown contains the Markdown report string.
        .error is set (non-None) if generation failed.
    """
    if not settings.ai_enabled:
        return ReportResult(
            report_markdown="",
            error="AI_DISABLED",
        )

    user_prompt = _build_metrics_prompt(metrics)

    try:
        report_md = chat_completion(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.4,
            max_tokens=1200,
        )
        logger.info("Management report generated successfully.")
        return ReportResult(report_markdown=report_md)

    except Exception as exc:
        logger.error("Report generation failed: %s", exc)
        return ReportResult(
            report_markdown="",
            error=str(exc),
        )


def _build_metrics_prompt(metrics: dict) -> str:
    """Format the metrics dict into a readable prompt for the LLM."""
    lines = [
        "Generate a management report for the following operational data.",
        "All figures below are pre-calculated — use them exactly as given.",
        "",
        f"Reporting Period: {metrics.get('period_label', 'All time')}",
        "",
        "--- Request Volume ---",
        f"Total requests:        {metrics.get('total_requests', 0)}",
        f"Submitted/Open:        {metrics.get('open_count', 0)}",
        f"In Progress:           {metrics.get('in_progress_count', 0)}",
        f"On Hold:               {metrics.get('on_hold_count', 0)}",
        f"Resolved:              {metrics.get('resolved_count', 0)}",
        f"Closed:                {metrics.get('closed_count', 0)}",
        f"Cancelled:             {metrics.get('cancelled_count', 0)}",
        "",
        "--- Priority Breakdown ---",
        f"Critical:              {metrics.get('critical_count', 0)}",
        f"High:                  {metrics.get('high_count', 0)}",
        f"Medium:                 {metrics.get('medium_count', 0)}",
        f"Low:                    {metrics.get('low_count', 0)}",
        "",
        "--- Performance ---",
    ]

    avg_hrs = metrics.get("avg_resolution_hours")
    if avg_hrs is not None:
        lines.append(f"Avg resolution time:   {avg_hrs:.1f} hours")
    else:
        lines.append("Avg resolution time:   N/A (no resolved requests)")

    med_hrs = metrics.get("median_resolution_hours")
    if med_hrs is not None:
        lines.append(f"Median resolution time: {med_hrs:.1f} hours")

    lines += [
        f"Unassigned requests:   {metrics.get('unassigned_count', 0)}",
        f"SLA breaches:          {metrics.get('sla_breach_count', 0)}",
        f"Overdue requests:      {metrics.get('overdue_count', 0)}",
        "",
        "--- Category Breakdown (most common categories) ---",
    ]

    category_breakdown = metrics.get("category_breakdown", {})
    if category_breakdown:
        for cat, count in sorted(category_breakdown.items(), key=lambda x: -x[1]):
            lines.append(f"  {cat.replace('_', ' ').title()}: {count}")
    else:
        lines.append("  No category data available.")

    # Recurring problem locations
    lines += ["", "--- Recurring Problem Locations (locations with 2+ requests) ---"]
    recurring_locations = metrics.get("recurring_locations", [])
    if recurring_locations:
        for loc in recurring_locations:
            lines.append(f"  {loc.get('location', 'Unknown')}: {loc.get('count', 0)} request(s)")
    else:
        lines.append("  No recurring location data available.")

    # Workload distribution
    lines += ["", "--- Technician Workload Distribution ---"]
    technician_summary = metrics.get("technician_summary", [])
    if technician_summary:
        for tech in technician_summary:
            lines.append(
                f"  {tech.get('name', 'Unknown')}: "
                f"{tech.get('assigned', 0)} total assigned, "
                f"{tech.get('open', 0)} currently open"
            )
    else:
        lines.append("  No technician data available.")

    # Overdue detail
    overdue_details = metrics.get("overdue_details", [])
    if overdue_details:
        lines += ["", "--- Overdue Request Details ---"]
        for od in overdue_details[:5]:
            lines.append(
                f"  {od.get('reference_number', '?')}: "
                f"{od.get('priority', '?')} priority, "
                f"{od.get('age_hours', 0):.0f} hours old, "
                f"SLA was {od.get('sla_hours', 0):.0f} hours"
            )

    return "\n".join(lines)
