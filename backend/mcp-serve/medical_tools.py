"""Medical knowledge retrieval tools for the Medical Health Agent."""

import json
import time

from medical.runtime import last_search_metrics, search_with_metrics
from medical.chat import contextual_facts_query, is_out_of_scope, is_urgent
from medical.evidence_contract import EvidenceBudget, build_evidence_pack


def register_medical_tools(mcp):
    @mcp.tool
    def search(query: str, top_k: int = 5, audience: str = "adult", region: str = "CN",
               prior_user_facts: str = "") -> str:
        """Search health evidence; respect each hit's usage_scope and never generalize beyond it. For a short follow-up, prior_user_facts may contain only facts explicitly stated by the user; never add assistant inferences."""
        started = time.perf_counter()
        budget = EvidenceBudget(max_chunks=max(1, min(top_k, 8)))
        empty_pack = build_evidence_pack([], budget)
        empty_evidence = {key: value for key, value in empty_pack.items() if key != "hits"}
        if audience != "adult" or region != "CN":
            return json.dumps({
                "query": query, "knowledge_status": "not_covered", "hits": [], "evidence": empty_evidence,
                "retrieval": {"search_type": "hybrid", "latency_ms": 0, "reason": "unsupported_audience_or_region"},
            }, ensure_ascii=False)
        retrieval_query = contextual_facts_query(query, prior_user_facts)
        urgency = "emergency" if is_urgent(retrieval_query) else "routine"
        if is_out_of_scope(retrieval_query):
            return json.dumps({
                "query": query, "knowledge_status": "not_covered", "hits": [], "evidence": empty_evidence,
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
            pack = build_evidence_pack(hits, budget)
            data = pack["hits"]
            diagnostics = last_search_metrics()
            return json.dumps({
                "query": query, "knowledge_status": "grounded" if data else "not_covered",
                "urgency": urgency, "scope": "general_health",
                "hits": data,
                "evidence": {key: value for key, value in pack.items() if key != "hits"},
                "retrieval": {
                    "search_type": "dense_bm25_rerank",
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    **diagnostics,
                },
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({
                "query": query, "knowledge_status": "unavailable", "hits": [], "evidence": empty_evidence,
                "urgency": urgency, "scope": "general_health",
                "retrieval": {"search_type": "dense_bm25_rerank", "latency_ms": round((time.perf_counter() - started) * 1000, 1), "error": type(exc).__name__},
            }, ensure_ascii=False)
