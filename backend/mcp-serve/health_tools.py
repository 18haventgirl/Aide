"""健康记录 MCP 工具，仅向 Medical Health Agent 暴露。"""

import json
from datetime import datetime
from typing import Any, Dict, Optional

from service.services.health_record_service import HealthRecordService
from core.database_core import DatabaseClient


def _parse_datetime(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


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
    ) -> str:
        """Save an explicit user health fact locally. Never pass inferred diagnoses."""
        if record_type not in {"symptom", "vital", "medication", "visit"}:
            return json.dumps({"success": False, "error": "invalid_record_type"}, ensure_ascii=False)
        try:
            details_dict = json.loads(details or "{}")
            if not isinstance(details_dict, dict):
                raise ValueError("details must be a JSON object")
            record = service.create_record(
                user_id, observed_at=_parse_datetime(observed_at), time_precision=time_precision,
                record_type=record_type, title=title[:200], summary=summary[:2000],
                details=details_dict, source="conversation",
                source_conversation_id=source_conversation_id or None,
                confidence=confidence,
            )
            if not record:
                return json.dumps({"success": False, "error": "create_failed"}, ensure_ascii=False)
            return json.dumps({"success": True, "record": record.to_dict()}, ensure_ascii=False)
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
    def update_record(user_id: int, record_id: int, summary: str = "", details: str = "{}") -> str:
        """Correct an existing user health record after the user clarifies it."""
        try:
            details_dict = json.loads(details or "{}")
            record = service.update_record(user_id, record_id, summary=summary[:2000], details=details_dict)
            if not record:
                return json.dumps({"success": False, "error": "not_found"}, ensure_ascii=False)
            return json.dumps({"success": True, "record": record.to_dict()}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"success": False, "error": type(exc).__name__}, ensure_ascii=False)
