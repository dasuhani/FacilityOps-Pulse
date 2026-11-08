"""
business/request_service.py
-----------------------------
Orchestrates the full lifecycle of a ServiceRequest.

This layer sits between the UI and the database/AI layers.
It is the only place that calls both CRUD operations and AI services together.

v3: Workflow statuses (Submitted → Assigned → In Progress → Resolved → Closed).
    Full comment system. AI recommendation approve/reject. Enriched detail view
    with comments and full request history.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from database.connection import get_db
from database.crud.request_crud import (
    create_request,
    get_request_by_id,
    get_request_by_reference,
    get_requests_for_requester,
    get_requests_for_technician,
    get_all_requests,
    get_open_requests_with_embeddings,
    update_request_status,
    update_request_ai_fields,
    update_request_priority,
    update_resolution_notes,
    update_request_v2_fields,
    count_requests_by_status,
    count_requests_by_category,
    count_requests_by_priority,
    write_request_history,
)
from database.crud.history_crud import (
    get_history_for_request,
    record_request_created,
)
from database.crud.audit_crud import (
    log_request_created,
    log_request_status_changed,
    log_request_assigned,
    log_request_cancelled,
    log_event,
)
from database.crud.comment_crud import (
    add_comment,
    get_comments_for_request,
)
from database.crud.location_crud import (
    get_all_locations,
    get_location_by_id,
    create_location,
)
from database.models.request import (
    RequestCategory,
    RequestPriority,
    RequestStatus,
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
)
from database.models.request_history import HistoryEventType
from database.models.location import Location
from services.ai.classifier import classify_request
from services.ai.priority_advisor import recommend_priority
from services.ai.similarity import (
    find_similar_requests,
    generate_and_store_embedding,
)
from core.config import settings
from core.security import sanitise_string

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Input validation constants
# ---------------------------------------------------------------------------
TITLE_MIN_LEN = 5
TITLE_MAX_LEN = 256
DESCRIPTION_MIN_LEN = 10
DESCRIPTION_MAX_LEN = 4000
LOCATION_MAX_LEN = 256
COMMENT_MAX_LEN = 4000


def _validate_request_input(
    title: str,
    description: str,
    location: str,
    location_id: Optional[int] = None,
) -> list[str]:
    """Return a list of validation error messages. Empty = valid."""
    errors: list[str] = []
    title = title.strip()
    description = description.strip()
    location = location.strip()

    if len(title) < TITLE_MIN_LEN:
        errors.append(f"Title must be at least {TITLE_MIN_LEN} characters.")
    if len(title) > TITLE_MAX_LEN:
        errors.append(f"Title must not exceed {TITLE_MAX_LEN} characters.")
    if len(description) < DESCRIPTION_MIN_LEN:
        errors.append(f"Description must be at least {DESCRIPTION_MIN_LEN} characters.")
    if len(description) > DESCRIPTION_MAX_LEN:
        errors.append(f"Description must not exceed {DESCRIPTION_MAX_LEN} characters.")
    if not location and not location_id:
        errors.append("Location is required — select a location or enter a custom one.")
    if location and len(location) > LOCATION_MAX_LEN:
        errors.append(f"Location must not exceed {LOCATION_MAX_LEN} characters.")
    return errors


# ---------------------------------------------------------------------------
# Location helpers
# ---------------------------------------------------------------------------

def get_active_locations() -> list[dict]:
    """Return all active locations for the submission form dropdown."""
    with get_db() as session:
        locs = get_all_locations(session, active_only=True)
        return [l.to_dict() for l in locs]


def get_location_by_id_view(location_id: int) -> Optional[dict]:
    with get_db() as session:
        loc = get_location_by_id(session, location_id)
        return loc.to_dict() if loc else None


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def submit_request(
    requester_id: int,
    title: str,
    description: str,
    location: str = "",
    category: RequestCategory = RequestCategory.OTHER,
    priority: RequestPriority = RequestPriority.MEDIUM,
    building: Optional[str] = None,
    floor_or_room: Optional[str] = None,
    location_id: Optional[int] = None,
    due_date: Optional[datetime] = None,
    run_ai: bool = True,
) -> dict:
    """
    Submit a new service request end-to-end.

    Steps:
      1. Validate input (title, description, location or location_id).
      2. If location_id provided, fetch its display_name for the free-text field.
      3. Persist the request with status SUBMITTED.
      4. Write initial status history + request history + audit log.
      5. Run AI classification (if enabled).
      6. Run AI priority recommendation (if enabled).
      7. Generate and store the semantic embedding.
      8. Return a result dict.

    Returns
    -------
    dict: success, errors, request, ai_classification, ai_priority, reference_number
    """
    # If a structured location was selected, resolve its display name
    if location_id and not location:
        loc_dict = get_location_by_id_view(location_id)
        if loc_dict:
            location = loc_dict["display_name"]
            if not building:
                building = loc_dict.get("building_name")
            if not floor_or_room and loc_dict.get("floor"):
                floor_or_room = loc_dict["floor"]

    errors = _validate_request_input(title, description, location, location_id)
    if errors:
        return {
            "success": False, "errors": errors, "request": None,
            "ai_classification": None, "ai_priority": None, "reference_number": None,
        }

    title = sanitise_string(title, TITLE_MAX_LEN)
    description = sanitise_string(description, DESCRIPTION_MAX_LEN)
    location = sanitise_string(location, LOCATION_MAX_LEN)

    ai_classification = None
    ai_priority = None

    with get_db() as session:
        req = create_request(
            session=session,
            requester_id=requester_id,
            title=title,
            description=description,
            location=location,
            category=category,
            priority=priority,
            building=sanitise_string(building or "", 128) or None,
            floor_or_room=sanitise_string(floor_or_room or "", 64) or None,
        )

        # Set v2 fields
        if location_id is not None:
            req.location_id = location_id
        if due_date is not None:
            req.due_date = due_date
        session.flush()

        # Initial status history (existing table)
        record_request_created(
            session=session,
            request_id=req.id,
            created_by_id=requester_id,
            created_by_role="requester",
        )

        # Request history (v2 richer log)
        write_request_history(
            session=session,
            request_id=req.id,
            changed_by=requester_id,
            event_type=HistoryEventType.CREATED,
            new_status=RequestStatus.SUBMITTED.value,
            note="Request submitted.",
        )

        # Audit log
        log_request_created(session, user_id=requester_id, request_id=req.id)

        # AI Classification
        if run_ai and settings.ai_enabled:
            try:
                ai_classification = classify_request(
                    title, description, user_category=category.value,
                )
                if ai_classification.succeeded:
                    update_request_ai_fields(
                        session=session,
                        request_id=req.id,
                        ai_suggested_category=ai_classification.category,
                        ai_classification_notes=(
                            ai_classification.summary
                            or ai_classification.notes
                            or ""
                        ),
                        ai_confidence_score=ai_classification.confidence,
                    )
                    # Store v2 AI fields: summary + recommended action
                    update_request_v2_fields(
                        session=session,
                        request_id=req.id,
                        ai_summary=ai_classification.summary or None,
                        ai_recommendation=ai_classification.recommended_action or None,
                    )
                    if not req.sub_category and ai_classification.sub_category:
                        req.sub_category = ai_classification.sub_category
                    if not req.department_target and ai_classification.department:
                        req.department_target = ai_classification.department
                    session.flush()
            except Exception as exc:
                logger.warning("AI classification step failed: %s", exc)

        # AI Priority — safety rules always applied, LLM is advisory only
        if run_ai:
            try:
                ai_priority = recommend_priority(
                    title=title,
                    description=description,
                    category=req.category.value,
                    location=location,
                )
                # ai_priority.succeeded may be False if AI is disabled,
                # but safety rules still ran and set the floor.
                if ai_priority.succeeded or ai_priority.error == "AI_DISABLED":
                    update_request_ai_fields(
                        session=session,
                        request_id=req.id,
                        ai_suggested_priority=ai_priority.priority,
                    )
                    # Apply the final priority (safety floor + LLM max)
                    # only when the submitter left it at the default MEDIUM.
                    if priority == RequestPriority.MEDIUM:
                        try:
                            req.priority = RequestPriority(ai_priority.priority)
                        except ValueError:
                            pass
                    session.flush()
            except Exception as exc:
                logger.warning("AI priority step failed: %s", exc)

        # Embedding
        if settings.semantic_search_enabled:
            generate_and_store_embedding(
                title=title,
                description=description,
                request_id=req.id,
                session=session,
            )

        ref = req.reference_number
        req_id = req.id

    logger.info(
        "Request submitted: ref=%s id=%s by requester_id=%s", ref, req_id, requester_id
    )

    with get_db() as session:
        fresh_req = get_request_by_id(session, req_id)

    return {
        "success": True,
        "errors": [],
        "request": fresh_req,
        "ai_classification": ai_classification,
        "ai_priority": ai_priority,
        "reference_number": ref,
    }


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def get_request_detail(request_id: int) -> Optional[dict]:
    """
    Return a fully-loaded request dict for the detail view.
    Includes requester name, assignment info, status history, comments,
    and full request history (v2 table).
    """
    with get_db() as session:
        req = get_request_by_id(session, request_id, load_relations=True)
        if not req:
            return None

        # StatusHistory (original table)
        status_history = get_history_for_request(session, request_id)

        # RequestHistory (v2 richer table)
        req_history = req.history if req.history else []

        # Comments (with user names)
        comments = get_comments_for_request(session, request_id, load_user=True)

        req_dict = req.to_dict()
        req_dict["requester_name"] = req.requester.full_name if req.requester else "Unknown"
        req_dict["history"] = [h.to_dict() for h in status_history]
        req_dict["request_history"] = [h.to_dict() for h in req_history]
        req_dict["comments"] = [
            {
                "id": c.id,
                "user_id": c.user_id,
                "user_name": c.user.full_name if c.user else "Unknown",
                "comment": c.comment,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in comments
        ]
        req_dict["assignment"] = req.assignment.to_dict() if req.assignment else None

        if req.assignment:
            tech = req.assignment.technician
            req_dict["technician_name"] = tech.full_name if tech else "Unknown"
            req_dict["technician_id"] = req.assignment.technician_id
        else:
            req_dict["technician_name"] = None
            req_dict["technician_id"] = None

    return req_dict


def get_requests_for_requester_view(
    requester_id: int,
    status_filter: Optional[list[str]] = None,
) -> list[dict]:
    status_enums = (
        [RequestStatus(s) for s in status_filter] if status_filter else None
    )
    with get_db() as session:
        reqs = get_requests_for_requester(
            session, requester_id, status_filter=status_enums
        )
        result = []
        for r in reqs:
            d = r.to_dict()
            d["technician_name"] = (
                r.assigned_technician.full_name if r.assigned_technician else None
            )
            result.append(d)
        return result


def get_requests_for_technician_view(
    technician_id: int,
    status_filter: Optional[list[str]] = None,
) -> list[dict]:
    status_enums = (
        [RequestStatus(s) for s in status_filter] if status_filter else None
    )
    with get_db() as session:
        reqs = get_requests_for_technician(
            session, technician_id, status_filter=status_enums
        )
        result = []
        for r in reqs:
            d = r.to_dict()
            d["requester_name"] = r.requester.full_name if r.requester else "Unknown"
            result.append(d)
        return result


def get_all_requests_admin(
    status_filter: Optional[list[str]] = None,
    category_filter: Optional[str] = None,
    priority_filter: Optional[str] = None,
    search_query: Optional[str] = None,
) -> list[dict]:
    status_enums = (
        [RequestStatus(s) for s in status_filter] if status_filter else None
    )
    cat_enum = RequestCategory(category_filter) if category_filter else None
    pri_enum = RequestPriority(priority_filter) if priority_filter else None

    with get_db() as session:
        reqs = get_all_requests(
            session,
            status_filter=status_enums,
            category_filter=cat_enum,
            priority_filter=pri_enum,
            search_query=search_query,
        )
        result = []
        for r in reqs:
            d = r.to_dict()
            d["requester_name"] = r.requester.full_name if r.requester else "Unknown"
            if r.assigned_technician:
                d["technician_name"] = r.assigned_technician.full_name
                d["technician_id"] = r.assigned_technician_id
            elif r.assignment:
                tech = r.assignment.technician
                d["technician_name"] = tech.full_name if tech else "Unassigned"
                d["technician_id"] = r.assignment.technician_id
            else:
                d["technician_name"] = "Unassigned"
                d["technician_id"] = None
            result.append(d)
        return result


# ---------------------------------------------------------------------------
# Comment system
# ---------------------------------------------------------------------------

def add_request_comment(
    request_id: int,
    user_id: int,
    comment: str,
    user_role: str = "requester",
) -> dict:
    """
    Add a comment to a request. Also writes a RequestHistory entry
    and an AuditLog entry.

    Returns
    -------
    dict: success, error, comment_id
    """
    comment_text = comment.strip()
    if not comment_text:
        return {"success": False, "error": "Comment must not be empty."}
    if len(comment_text) > COMMENT_MAX_LEN:
        return {
            "success": False,
            "error": f"Comment must not exceed {COMMENT_MAX_LEN} characters.",
        }

    try:
        with get_db() as session:
            c = add_comment(session, request_id, user_id, comment_text)

            # Request history
            write_request_history(
                session=session,
                request_id=request_id,
                changed_by=user_id,
                event_type=HistoryEventType.COMMENT_ADDED,
                note=comment_text[:200],
            )

            # Audit log
            log_event(
                session,
                action="request.comment_added",
                user_id=user_id,
                entity_type="request",
                entity_id=request_id,
                detail={"role": user_role, "preview": comment_text[:100]},
            )

            comment_id = c.id

        return {"success": True, "error": None, "comment_id": comment_id}

    except ValueError as exc:
        return {"success": False, "error": str(exc), "comment_id": None}
    except Exception as exc:
        logger.error("Failed to add comment to request %s: %s", request_id, exc)
        return {
            "success": False,
            "error": "Failed to add comment. Please try again.",
            "comment_id": None,
        }


def get_comments_for_request_view(request_id: int) -> list[dict]:
    """Return all comments for a request as dicts with user names."""
    with get_db() as session:
        comments = get_comments_for_request(session, request_id, load_user=True)
        return [
            {
                "id": c.id,
                "user_id": c.user_id,
                "user_name": c.user.full_name if c.user else "Unknown",
                "comment": c.comment,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in comments
        ]


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------

def technician_update_status(
    request_id: int,
    new_status: str,
    technician_id: int,
    note: Optional[str] = None,
    resolution_notes: Optional[str] = None,
) -> dict:
    """
    Allow a technician to update the status of an assigned request.
    Enforces that only the assigned technician can update.

    Allowed transitions for technicians:
      ASSIGNED → IN_PROGRESS
      IN_PROGRESS → ON_HOLD
      ON_HOLD → IN_PROGRESS
      IN_PROGRESS → RESOLVED (requires resolution notes)
    """
    allowed_statuses = {
        RequestStatus.IN_PROGRESS.value,
        RequestStatus.ON_HOLD.value,
        RequestStatus.RESOLVED.value,
    }
    if new_status not in allowed_statuses:
        return {
            "success": False,
            "error": (
                f"Technicians may only set status to: "
                f"{', '.join(sorted(allowed_statuses))}."
            ),
        }

    # Resolving requires resolution notes
    if new_status == RequestStatus.RESOLVED.value and not (resolution_notes or "").strip():
        return {
            "success": False,
            "error": "Resolution notes are required when marking a request as Resolved.",
        }

    with get_db() as session:
        req = get_request_by_id(session, request_id)
        if not req:
            return {"success": False, "error": "Request not found."}

        # Verify assignment ownership
        if req.assignment is None or req.assignment.technician_id != technician_id:
            log_event(
                session,
                action="request.status_changed",
                user_id=technician_id,
                entity_type="request",
                entity_id=request_id,
                detail={"attempted_status": new_status},
                outcome="denied",
            )
            return {"success": False, "error": "This request is not assigned to you."}

        old_status = req.status.value

        if resolution_notes:
            update_resolution_notes(session, request_id, resolution_notes)

        update_request_status(
            session=session,
            request_id=request_id,
            new_status=RequestStatus(new_status),
            changed_by_id=technician_id,
            changed_by_role="technician",
            note=sanitise_string(note or "", 1000),
        )

        # Request history (v2)
        write_request_history(
            session=session,
            request_id=request_id,
            changed_by=technician_id,
            event_type=HistoryEventType.STATUS_CHANGE,
            old_status=old_status,
            new_status=new_status,
            note=sanitise_string(note or "", 1000) or None,
        )

        # Audit log
        log_request_status_changed(
            session, user_id=technician_id, request_id=request_id,
            old_status=old_status, new_status=new_status,
        )

    return {"success": True, "error": None}


def admin_update_status(
    request_id: int,
    new_status: str,
    admin_id: int,
    note: Optional[str] = None,
) -> dict:
    """Admin can set any valid status on any request."""
    try:
        status_enum = RequestStatus(new_status)
    except ValueError:
        return {"success": False, "error": f"Invalid status: {new_status}"}

    with get_db() as session:
        req = get_request_by_id(session, request_id)
        if not req:
            return {"success": False, "error": "Request not found."}

        old_status = req.status.value

        update_request_status(
            session=session,
            request_id=request_id,
            new_status=status_enum,
            changed_by_id=admin_id,
            changed_by_role="admin",
            note=sanitise_string(note or "", 1000),
        )

        write_request_history(
            session=session,
            request_id=request_id,
            changed_by=admin_id,
            event_type=HistoryEventType.STATUS_CHANGE,
            old_status=old_status,
            new_status=new_status,
            note=sanitise_string(note or "", 1000) or None,
        )

        log_request_status_changed(
            session, user_id=admin_id, request_id=request_id,
            old_status=old_status, new_status=new_status,
        )

    return {"success": True, "error": None}


def admin_assign_request(
    request_id: int,
    technician_id: int,
    admin_id: int,
    assignment_notes: Optional[str] = None,
) -> dict:
    """
    Admin assigns (or re-assigns) a technician to a request.
    Writes RequestHistory(ASSIGNMENT/REASSIGNMENT) + AuditLog.
    The assignment_crud layer transitions SUBMITTED→ASSIGNED automatically.
    """
    from database.crud.assignment_crud import assign_request, get_assignment_by_request

    with get_db() as session:
        # Check if re-assignment
        existing = get_assignment_by_request(session, request_id)
        is_reassign = existing is not None

        assign_request(
            session=session,
            request_id=request_id,
            technician_id=technician_id,
            assigned_by_id=admin_id,
            assignment_notes=assignment_notes,
        )

        # Request history
        write_request_history(
            session=session,
            request_id=request_id,
            changed_by=admin_id,
            event_type=(
                HistoryEventType.REASSIGNMENT if is_reassign
                else HistoryEventType.ASSIGNMENT
            ),
            note=f"Assigned to technician id={technician_id}."
                 + (f" Notes: {assignment_notes}" if assignment_notes else ""),
        )

        # Audit log
        log_request_assigned(
            session, admin_id=admin_id, request_id=request_id,
            technician_id=technician_id,
        )

    return {"success": True, "error": None}


def admin_unassign_request(
    request_id: int,
    admin_id: int,
) -> dict:
    """Admin removes the technician assignment. Returns request to SUBMITTED."""
    from database.crud.assignment_crud import unassign_request

    with get_db() as session:
        unassign_request(session, request_id, unassigned_by_id=admin_id)

        write_request_history(
            session=session,
            request_id=request_id,
            changed_by=admin_id,
            event_type=HistoryEventType.UNASSIGNMENT,
            note="Assignment removed by admin.",
        )

        log_event(
            session,
            action="request.unassigned",
            user_id=admin_id,
            entity_type="request",
            entity_id=request_id,
        )

    return {"success": True, "error": None}


def cancel_request(request_id: int, requester_id: int) -> dict:
    """
    A requester can cancel their own SUBMITTED request.
    Cannot cancel once assigned or in progress.
    """
    with get_db() as session:
        req = get_request_by_id(session, request_id)
        if not req:
            return {"success": False, "error": "Request not found."}
        if req.requester_id != requester_id:
            log_event(
                session,
                action="request.cancelled",
                user_id=requester_id,
                entity_type="request",
                entity_id=request_id,
                detail={"reason": "not_owner"},
                outcome="denied",
            )
            return {"success": False, "error": "You can only cancel your own requests."}

        # Only submitted or legacy-open requests can be cancelled by the requester
        cancellable = {RequestStatus.SUBMITTED.value, RequestStatus.OPEN.value}
        if req.status.value not in cancellable:
            return {
                "success": False,
                "error": (
                    f"Cannot cancel a request with status '{req.status.value}'. "
                    "Only Submitted requests can be cancelled by the requester."
                ),
            }

        old_status = req.status.value

        update_request_status(
            session=session,
            request_id=request_id,
            new_status=RequestStatus.CANCELLED,
            changed_by_id=requester_id,
            changed_by_role="requester",
            note="Cancelled by requester.",
        )

        write_request_history(
            session=session,
            request_id=request_id,
            changed_by=requester_id,
            event_type=HistoryEventType.STATUS_CHANGE,
            old_status=old_status,
            new_status=RequestStatus.CANCELLED.value,
            note="Cancelled by requester.",
        )

        log_request_cancelled(session, user_id=requester_id, request_id=request_id)

    return {"success": True, "error": None}


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def check_for_similar_requests(title: str, description: str) -> list[dict]:
    if not settings.semantic_search_enabled:
        return []

    with get_db() as session:
        candidates = get_open_requests_with_embeddings(session)
        similar = find_similar_requests(
            new_title=title,
            new_description=description,
            candidate_requests=candidates,
        )

    return [
        {
            "request_id": s.request_id,
            "reference_number": s.reference_number,
            "title": s.title,
            "status": s.status,
            "similarity_score": s.similarity_score,
            "similarity_pct": f"{s.similarity_score * 100:.0f}%",
        }
        for s in similar
    ]


# ---------------------------------------------------------------------------
# Priority override (admin)
# ---------------------------------------------------------------------------

def admin_override_priority(
    request_id: int,
    new_priority: str,
    admin_id: int,
) -> dict:
    try:
        priority_enum = RequestPriority(new_priority)
    except ValueError:
        return {"success": False, "error": f"Invalid priority: {new_priority}"}

    with get_db() as session:
        req = get_request_by_id(session, request_id)
        if not req:
            return {"success": False, "error": "Request not found."}

        old_priority = req.priority.value
        update_request_priority(session, request_id, priority_enum, admin_id)

        write_request_history(
            session=session,
            request_id=request_id,
            changed_by=admin_id,
            event_type=HistoryEventType.PRIORITY_CHANGE,
            field_name="priority",
            old_value=old_priority,
            new_value=new_priority,
        )

        log_event(
            session,
            action="request.priority_changed",
            user_id=admin_id,
            entity_type="request",
            entity_id=request_id,
            detail={"old": old_priority, "new": new_priority},
        )

    return {"success": True, "error": None}


# ---------------------------------------------------------------------------
# AI recommendation approve / reject (admin)
# ---------------------------------------------------------------------------

def admin_review_ai_recommendation(
    request_id: int,
    admin_id: int,
    action: str,
    notes: Optional[str] = None,
) -> dict:
    """
    Admin approves or rejects the AI-suggested category and/or priority.

    action: "approve_category" | "approve_priority" | "reject" | "approve_all"
    """
    valid_actions = {"approve_category", "approve_priority", "reject", "approve_all"}
    if action not in valid_actions:
        return {"success": False, "error": f"Invalid action: {action}"}

    with get_db() as session:
        req = get_request_by_id(session, request_id)
        if not req:
            return {"success": False, "error": "Request not found."}

        changes = []

        if action in ("approve_category", "approve_all"):
            if req.ai_suggested_category:
                try:
                    new_cat = RequestCategory(req.ai_suggested_category)
                    old_cat = req.category.value
                    req.category = new_cat
                    changes.append(f"category: {old_cat} → {new_cat.value}")
                except ValueError:
                    pass

        if action in ("approve_priority", "approve_all"):
            if req.ai_suggested_priority:
                try:
                    new_pri = RequestPriority(req.ai_suggested_priority)
                    old_pri = req.priority.value
                    req.priority = new_pri
                    changes.append(f"priority: {old_pri} → {new_pri.value}")
                except ValueError:
                    pass

        if action == "reject":
            # Clear the AI suggestions so they don't keep showing
            req.ai_classification_notes = (
                f"[REJECTED by admin] {req.ai_classification_notes or ''}"
            ).strip()

        session.flush()

        # History + audit
        write_request_history(
            session=session,
            request_id=request_id,
            changed_by=admin_id,
            event_type=HistoryEventType.FIELD_EDIT,
            field_name="ai_recommendation",
            old_value=None,
            new_value=action,
            note="; ".join(changes) if changes else (notes or f"AI recommendation {action}"),
        )

        log_event(
            session,
            action=f"request.ai_{action}",
            user_id=admin_id,
            entity_type="request",
            entity_id=request_id,
            detail={"changes": changes, "notes": notes},
        )

    return {"success": True, "error": None}


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------

def get_status_counts() -> dict[str, int]:
    """Return {status_value: count} using the business layer."""
    with get_db() as session:
        return count_requests_by_status(session)


# ---------------------------------------------------------------------------
# Technician recommendation (AI-assisted, admin approves)
# ---------------------------------------------------------------------------

def get_technician_recommendations(
    request_id: int,
    top_k: int = 3,
) -> list[dict]:
    """
    Get AI-assisted technician recommendations for a specific request.

    Uses the request's category to match technician skills, combined
    with current workload balancing.  Never auto-assigns — the admin
    must approve every assignment.

    Returns a list of dicts with:
      technician_id, technician_name, score, skill_match,
      skills_matched, current_workload, reasons
    """
    from services.ai.technician_recommender import recommend_technicians

    with get_db() as session:
        req = get_request_by_id(session, request_id)
        if not req:
            return []

        recs = recommend_technicians(
            session=session,
            request_category=req.category.value,
            top_k=top_k,
        )
        return [
            {
                "technician_id": r.technician_id,
                "technician_name": r.technician_name,
                "score": r.score,
                "skill_match": r.skill_match,
                "skills_matched": r.skills_matched,
                "current_workload": r.current_workload,
                "reasons": r.reasons,
            }
            for r in recs
        ]


# ---------------------------------------------------------------------------
# Natural-language query (admin only, controlled intents)
# ---------------------------------------------------------------------------

def answer_natural_language_query(question: str) -> dict:
    """
    Answer a natural-language question about facility operations.

    The LLM classifies the question into a predefined intent (never
    generates SQL).  A Python function executes the corresponding
    database query.  The result is returned as structured data + a
    human-readable answer.

    Returns
    -------
    dict with keys: question, intent, answer, data, error
    """
    from services.ai.nl_query import answer_query

    result = answer_query(question)
    return {
        "question": result.question,
        "intent": result.intent,
        "answer": result.answer,
        "data": result.data,
        "error": result.error,
    }
