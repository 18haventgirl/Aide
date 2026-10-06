"""健康记录 MCP 工具，仅向 Medical Health Agent 暴露。"""

import json
from datetime import datetime
from typing import Any, Dict, Optional

from service.services.health_record_service import HealthRecordService
from service.services.health_time import resolve_health_time, HealthTimeClarification
from core.database_core import DatabaseClient


def _resolve_observed_at(value: Optional[str], date_text: str, precision: str) -> tuple[datetime, str]:
    result = resolve_health_time(value or "", date_text, precision)
    return result.observed_at, result.precision


def register_health_tools(mcp):
    db = DatabaseClient()
    db.initialize()
    db.create_tables()
    service = HealthRecordService(db)

    @mcp.tool
    def create_record(
        user_id: int,
        record_type: str,
        title: str,
        summary: str = "",
        observed_at: str = "",
        time_precision: str = "minute",
        details: str = "{}",
        confidence: str = "explicit",
        source_conversation_id: str = "",
        date_text: str = "",
        source_message_id: str = "",
        idempotency_key: str = "",
    ) -> str:
        """Save an explicit user health fact locally. Never pass inferred diagnoses."""
        if record_type not in {"symptom", "vital", "medication", "visit"}:
            return json.dumps({"success": False, "error": "invalid_record_type"}, ensure_ascii=False)
        try:
            details_dict = json.loads(details or "{}")
            if not isinstance(details_dict, dict):
                raise ValueError("details must be a JSON object")
            resolved = resolve_health_time(observed_at, date_text or f"{title} {summary}", time_precision)
            details_dict = {**details_dict, "_time": {"expression": resolved.date_text,
                "precision": resolved.precision, "parser_version": resolved.parser_version}}
            record = service.create_record(
                user_id, observed_at=resolved.observed_at, time_precision=resolved.precision,
                record_type=record_type, title=title[:200], summary=summary[:2000],
                details=details_dict, source="conversation",
                source_conversation_id=source_conversation_id or None,
                source_message_id=source_message_id or None,
                confidence="inferred_time" if resolved.precision == "unknown" else confidence,
                idempotency_key=idempotency_key or None,
            )
            if not record:
                return json.dumps({"success": False, "error": "create_failed"}, ensure_ascii=False)
            return json.dumps({"success": True, "record": record.to_dict()}, ensure_ascii=False)
        except HealthTimeClarification as exc:
            return json.dumps({"success": False, "error": "needs_clarification",
                               "reason": exc.reason, "question": exc.question}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"success": False, "error": type(exc).__name__}, ensure_ascii=False)

    @mcp.tool
    def get_records(user_id: int, start_date: str = "", end_date: str = "", limit: int = 100) -> str:
        """Read the user's own health records for a date range."""
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
            end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
            records = service.list_records(user_id, start, end, max(1, min(limit, 500)))
            return json.dumps({"success": True, "records": [r.to_dict() for r in records]}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"success": False, "error": type(exc).__name__}, ensure_ascii=False)

    @mcp.tool
    def get_record(user_id: int, record_id: int) -> str:
        """Read one of the user's health record details."""
        record = service.get_record(user_id, record_id)
        if not record:
            return json.dumps({"success": False, "error": "not_found"}, ensure_ascii=False)
        return json.dumps({"success": True, "record": record.to_dict()}, ensure_ascii=False)

    @mcp.tool
    def update_record(user_id: int, record_id: int, summary: Optional[str] = None,
                      details: Optional[str] = None, observed_at: str = "", date_text: str = "",
                      time_precision: str = "minute") -> str:
        """Correct an existing user health record after the user clarifies it."""
        try:
            current = service.get_record(user_id, record_id)
            if not current:
                return json.dumps({"success": False, "error": "not_found"}, ensure_ascii=False)
            changes = {}
            if summary is not None:
                changes["summary"] = summary[:2000]
            if details is not None:
                supplied = json.loads(details)
                if not isinstance(supplied, dict):
                    raise ValueError("details must be a JSON object")
                changes["details"] = {**current.details, **supplied}
            if observed_at or date_text:
                resolved = resolve_health_time(observed_at, date_text, time_precision)
                changes.update(observed_at=resolved.observed_at, time_precision=resolved.precision)
                changes["details"] = {**changes.get("details", current.details), "_time": {
                    "expression": resolved.date_text, "precision": resolved.precision,
                    "parser_version": resolved.parser_version}}
            record = service.update_record(user_id, record_id, **changes)
            if not record:
                return json.dumps({"success": False, "error": "not_found"}, ensure_ascii=False)
            return json.dumps({"success": True, "record": record.to_dict()}, ensure_ascii=False)
        except HealthTimeClarification as exc:
            return json.dumps({"success": False, "error": "needs_clarification",
                               "reason": exc.reason, "question": exc.question}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"success": False, "error": type(exc).__name__}, ensure_ascii=False)
