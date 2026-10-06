"""Health tools bind identity/provenance in local SDK context, never model arguments."""
import asyncio
from datetime import datetime
import hashlib
import json
from typing import Any, Literal

from agents import RunContextWrapper, function_tool
from service.services.health_record_service import HealthRecordService, HealthRecordConflict
from service.services.health_time import resolve_health_time, HealthTimeClarification


def _service():
    from service.service_manager import service_manager
    return service_manager.get_service("health_record_service", HealthRecordService)


def _context(ctx, write=False):
    context = ctx.context
    if not getattr(context, "user_id", None):
        raise ValueError("health_context_missing")
    if write and (not context.conversation_id or not context.health_message_id or context.health_reference_at is None):
        raise ValueError("health_message_context_missing")
    return context


def _result(operation):
    try:
        return json.dumps(operation(), ensure_ascii=False)
    except HealthTimeClarification as exc:
        return json.dumps({"success": False, "error": "needs_clarification",
                           "reason": exc.reason, "question": exc.question}, ensure_ascii=False)
    except HealthRecordConflict as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    except ValueError as exc:
        reason = str(exc)
        code = reason if reason in {"health_context_missing", "health_message_context_missing"} else "invalid_fact_fields"
        return json.dumps({"success": False, "error": code}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"success": False, "error": type(exc).__name__}, ensure_ascii=False)


def _details(value):
    result = json.loads(value)
    if not isinstance(result, dict) or any(key.startswith("_") for key in result):
        raise ValueError("details must contain public fact fields")
    return result


def _time_details(details, resolved):
    return {**details, "_time": {"expression": resolved.date_text,
                               "precision": resolved.precision, "parser_version": resolved.parser_version}}


@function_tool
async def health_create_record(ctx: RunContextWrapper[Any],
    record_type: Literal["symptom", "vital", "medication", "visit"], title: str,
    summary: str = "", date_text: str = "", observed_at: str = "",
    time_precision: Literal["minute", "day", "unknown"] = "unknown",
    details: str = "{}", event_index: int = 0) -> str:
    """Record one explicit current-user fact. Keep event_index stable (0,1,...) for distinct facts in this user message; a retry uses the same index. Pass the user's original date expression; never invent a month. Identity and source are supplied by the application."""
    def operation():
        context = _context(ctx, write=True)
        if not 0 <= event_index <= 19:
            raise ValueError("invalid event_index")
        resolved = resolve_health_time(observed_at, date_text or f"{title} {summary}",
                                      time_precision, reference=context.health_reference_at)
        key = hashlib.sha256(f"health-create-v1:{context.user_id}:{context.conversation_id}:{context.health_message_id}:{event_index}".encode()).hexdigest()
        record = _service().create_record(context.user_id, observed_at=resolved.observed_at,
            time_precision=resolved.precision, record_type=record_type, title=title, summary=summary,
            details=_time_details(_details(details), resolved), source="conversation",
            source_conversation_id=context.conversation_id, source_message_id=context.health_message_id,
            confidence=resolved.confidence, idempotency_key=key)
        return {"success": True, "record": record.to_dict()}
    return await asyncio.to_thread(_result, operation)


@function_tool
async def health_get_records(ctx: RunContextWrapper[Any], start_date: str = "", end_date: str = "", limit: int = 100) -> str:
    """Read current user's health facts for a bounded date range. Use these facts, dates and IDs for cross-conversation summaries, not inferred diagnoses."""
    def operation():
        context = _context(ctx)
        start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
        end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
        records = _service().list_records(context.user_id, start, end, max(1, min(limit, 500)))
        return {"success": True, "records": [r.to_dict() for r in records]}
    return await asyncio.to_thread(_result, operation)


@function_tool
async def health_get_record(ctx: RunContextWrapper[Any], record_id: int) -> str:
    """Read a current-user record before making a correction."""
    def operation():
        record = _service().get_record(_context(ctx).user_id, record_id)
        return {"success": True, "record": record.to_dict()} if record else {"success": False, "error": "not_found"}
    return await asyncio.to_thread(_result, operation)


@function_tool
async def health_update_record(ctx: RunContextWrapper[Any], record_id: int,
    summary: str | None = None, details: str | None = None, date_text: str = "",
    observed_at: str = "", time_precision: Literal["minute", "day", "unknown"] = "minute",
    expected_revision: int | None = None) -> str:
    """Correct the identified record after user clarification. Omitted fields stay unchanged; fetch the record first if its identity is uncertain."""
    def operation():
        context = _context(ctx, write=True)
        service = _service()
        current = service.get_record(context.user_id, record_id)
        if current is None:
            return {"success": False, "error": "not_found"}
        changes = {}
        if summary is not None:
            changes["summary"] = summary
        if details is not None:
            changes["details"] = {**current.details, **_details(details)}
        if date_text or observed_at:
            resolved = resolve_health_time(observed_at, date_text, time_precision, reference=context.health_reference_at)
            changes.update(observed_at=resolved.observed_at, time_precision=resolved.precision)
            changes["details"] = _time_details(changes.get("details", current.details), resolved)
        record = service.update_record(context.user_id, record_id,
            expected_revision=expected_revision if expected_revision is not None else current.to_dict()["revision"],
            actor_message_id=context.health_message_id, **changes)
        return {"success": True, "record": record.to_dict()}
    return await asyncio.to_thread(_result, operation)


def health_function_tools():
    return [health_create_record, health_get_records, health_get_record, health_update_record]
