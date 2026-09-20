"""Medical knowledge retrieval tools for the Medical Health Agent."""

import json
import time

from medical.runtime import search_with_metrics


def register_medical_tools(mcp):
    @mcp.tool
    def medical_search(query: str, top_k: int = 5, audience: str = "adult", region: str = "CN") -> str:
        """Search the reviewed Chinese health knowledge base. This tool retrieves evidence only; the Agent writes the answer."""
        started = time.perf_counter()
        if audience != "adult" or region != "CN":
            return json.dumps({
                "query": query, "knowledge_status": "not_covered", "hits": [],
                "retrieval": {"search_type": "hybrid", "latency_ms": 0, "reason": "unsupported_audience_or_region"},
            }, ensure_ascii=False)
        try:
            # Startup can race with the first two agent tool calls while the
            # local Chroma tenant and BGE model are being initialized. Retry
            # one transient initialization failure before reporting the tool
            # as unavailable to the LLM.
            last_error = None
            for attempt in range(2):
                try:
                    hits = search_with_metrics(query.strip()[:1000], preview=False, limit=max(1, min(top_k, 8)))
                    break
                except (RuntimeError, ValueError) as exc:
                    last_error = exc
                    if attempt == 1:
                        raise
                    time.sleep(0.15)
            data = [{
                "evidence_id": f"E{i}", "doc_id": hit.doc_id, "title": hit.title,
                "section_path": hit.section_path, "text": hit.text[:1600],
                "source_url": hit.source_url, "source_org": hit.source_org,
                "reviewed_at": hit.reviewed_at.isoformat() if hit.reviewed_at else None,
            } for i, hit in enumerate(hits, 1)]
            return json.dumps({
                "query": query, "knowledge_status": "grounded" if data else "not_covered",
                "hits": data,
                "retrieval": {"search_type": "hybrid", "latency_ms": round((time.perf_counter() - started) * 1000, 1)},
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({
                "query": query, "knowledge_status": "unavailable", "hits": [],
                "retrieval": {"search_type": "hybrid", "latency_ms": round((time.perf_counter() - started) * 1000, 1), "error": type(exc).__name__},
            }, ensure_ascii=False)
