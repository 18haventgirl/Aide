"""Medical knowledge retrieval tools for the Medical Health Agent."""

import json
import time

from medical.runtime import last_search_metrics, search_with_metrics
from medical.chat import contextual_facts_query, is_out_of_scope, is_urgent


def register_medical_tools(mcp):
    @mcp.tool
    def search(query: str, top_k: int = 5, audience: str = "adult", region: str = "CN",
               prior_user_facts: str = "") -> str:
        """Search reviewed health evidence. For a short follow-up, prior_user_facts may contain only facts explicitly stated by the user; never add assistant inferences."""
        started = time.perf_counter()
        if audience != "adult" or region != "CN":
            return json.dumps({
                "query": query, "knowledge_status": "not_covered", "hits": [],
                "retrieval": {"search_type": "hybrid", "latency_ms": 0, "reason": "unsupported_audience_or_region"},
            }, ensure_ascii=False)
        retrieval_query = contextual_facts_query(query, prior_user_facts)
        urgency = "emergency" if is_urgent(retrieval_query) else "routine"
        if is_out_of_scope(retrieval_query):
            return json.dumps({
                "query": query, "knowledge_status": "not_covered", "hits": [],
                "urgency": urgency, "scope": "clinical_decision",
                "retrieval": {"search_type": "scope_gate", "latency_ms": 0},
            }, ensure_ascii=False)
        try:
            # Startup can race with the first two agent tool calls while the
            # local Chroma tenant and BGE model are being initialized. Retry
            # one transient initialization failure before reporting the tool
            # as unavailable to the LLM.
            last_error = None
            for attempt in range(2):
                try:
                    hits = search_with_metrics(retrieval_query[:1000], preview=False, limit=max(1, min(top_k, 8)))
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
                "status": hit.status,
                "relevance_score": (round(hit.rerank_score, 4)
                                    if hit.rerank_score is not None else None),
            } for i, hit in enumerate(hits, 1)]
            diagnostics = last_search_metrics()
            return json.dumps({
                "query": query, "knowledge_status": "grounded" if data else "not_covered",
                "urgency": urgency, "scope": "general_health",
                "hits": data,
                "retrieval": {
                    "search_type": "dense_bm25_rerank",
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    **diagnostics,
                },
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({
                "query": query, "knowledge_status": "unavailable", "hits": [],
                "urgency": urgency, "scope": "general_health",
                "retrieval": {"search_type": "dense_bm25_rerank", "latency_ms": round((time.perf_counter() - started) * 1000, 1), "error": type(exc).__name__},
            }, ensure_ascii=False)
