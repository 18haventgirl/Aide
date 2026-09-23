"""Parse medical tool results into safe response metadata.

The model receives the full evidence text.  The UI and database only need the
source identity and coverage state, so this module deliberately drops the
query, evidence text, and retrieval scores from persisted message metadata.
"""

from __future__ import annotations

import json
from typing import Any


def _as_payload(value: Any) -> dict | None:
    if isinstance(value, dict):
        if "knowledge_status" in value and "hits" in value:
            return value
        for key in ("data", "result", "structured_content", "structuredContent"):
            nested = _as_payload(value.get(key))
            if nested:
                return nested
        return None
    if isinstance(value, str):
        try:
            return _as_payload(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return None
    if isinstance(value, (list, tuple)):
        for item in value:
            nested = _as_payload(item)
            if nested:
                return nested
        return None
    text = getattr(value, "text", None)
    if isinstance(text, str):
        return _as_payload(text)
    content = getattr(value, "content", None)
    if content is not None:
        return _as_payload(content)
    return None


def medical_response_metadata(tool_output: Any) -> dict | None:
    """Return persistable coverage and citations for a medical search output."""
    payload = _as_payload(tool_output)
    if payload is None:
        return None
    status = payload.get("knowledge_status")
    if status not in {"grounded", "not_covered", "unavailable"}:
        return None
    citations: list[dict] = []
    seen: set[str] = set()
    for index, hit in enumerate(payload.get("hits") or [], 1):
        if not isinstance(hit, dict):
            continue
        doc_id = str(hit.get("doc_id") or "").strip()
        title = str(hit.get("title") or "").strip()
        url = str(hit.get("source_url") or "").strip()
        if not doc_id or not title or not url or doc_id in seen:
            continue
        seen.add(doc_id)
        citations.append({
            "evidence_id": str(hit.get("evidence_id") or f"E{index}"),
            "doc_id": doc_id,
            "title": title,
            "url": url,
            "source_org": str(hit.get("source_org") or ""),
            "reviewed_at": hit.get("reviewed_at"),
            "status": hit.get("status"),
        })
    urgency = payload.get("urgency") if payload.get("urgency") in {"routine", "emergency"} else None
    scope = payload.get("scope") if payload.get("scope") in {"general_health", "clinical_decision"} else None
    return {
        "knowledge_status": status, "citations": citations,
        "medical_urgency": urgency, "medical_scope": scope,
    }
