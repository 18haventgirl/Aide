"""Evaluation at the actual MCP evidence budget, with errors kept in denominators."""
from dataclasses import asdict
import time

from ..chat import contextual_facts_query, is_out_of_scope, is_urgent
from ..evaluate import validate_cases, QUERY_CONTRACT
from ..evidence_contract import EvidenceBudget, build_evidence_pack, canonical_hash
from ..source_provenance import SourceResolver
from .metrics import validate_references, score_ranges


def evaluate_evidence(searcher, cases, documents, budget=None):
    validate_cases(cases)
    validate_references(cases, documents)
    resolver = SourceResolver(documents)
    budget = budget or EvidenceBudget()
    rows = []
    positive = followup = negative = urgent = rejected = urgent_ok = errors = 0
    doc_recall = followup_recall = union_recall = pool_recall = 0.0
    union_count = pool_count = labelled = 0
    totals = {key: 0 for key in ("evidence_spans", "retained_spans", "critical_conditions", "retained_conditions")}
    relevant_chunks = judged_chunks = 0
    for case in cases:
        kind = case.get("kind", "supported")
        expected = set(case.get("expected_doc_ids", []))
        if kind in {"supported", "followup"}:
            positive += 1
            followup += kind == "followup"
        negative += kind == "unanswerable"
        urgent += kind == "urgent"
        refs = case.get("expected_evidence", [])
        labelled += bool(refs)
        for reference in refs:
            totals["evidence_spans"] += len(reference["ranges"])
            totals["critical_conditions"] += len(reference.get("required_conditions", []))
        row = {"id": case["id"], "kind": kind, "status": "ok"}
        started = time.perf_counter()
        try:
            if kind == "urgent":
                row["urgent_detected"] = is_urgent(case["query"])
                urgent_ok += row["urgent_detected"]
                row["status"] = "rule_only_not_agent_test"
            else:
                query = contextual_facts_query(case["query"], case["history"] if kind == "followup" else "")
                gated = is_out_of_scope(query)
                hits = [] if gated else searcher.search(query[:1000], limit=budget.max_chunks)
                pack = build_evidence_pack(hits, budget, resolver)
                found = set(hit["doc_id"] for hit in pack["hits"])
                row.update(evidence_pack=pack, query_sha256=canonical_hash(query),
                           expected=sorted(expected), retrieved=list(dict.fromkeys(h["doc_id"] for h in pack["hits"])),
                           scope_gated=gated, diagnostics=searcher.search_metrics() if not gated and hasattr(searcher, "search_metrics") else {})
                if expected:
                    recall = len(expected & found)/len(expected)
                    row["document_recall_at_budget"] = recall
                    trace = searcher.candidate_trace() if not gated and hasattr(searcher, "candidate_trace") else {}
                    for name in ("union", "rerank_pool"):
                        if name in trace:
                            stage_ids = {h.doc_id for h in trace[name]}
                            value = len(expected & stage_ids)/len(expected)
                            row[f"candidate_{name}_recall"] = value
                if kind == "unanswerable":
                    row["rejected"] = not bool(pack["hits"])
                ranges = score_ranges(pack, refs, resolver.documents)
                row["range_metrics"] = ranges
                totals["retained_spans"] += ranges["retained_spans"]
                totals["retained_conditions"] += ranges["retained_conditions"]
                if expected:
                    doc_recall += recall
                    followup_recall += recall if kind == "followup" else 0
                    if "candidate_union_recall" in row:
                        union_recall += row["candidate_union_recall"]; union_count += 1
                    if "candidate_rerank_pool_recall" in row:
                        pool_recall += row["candidate_rerank_pool_recall"]; pool_count += 1
                rejected += row.get("rejected", False)
                if refs:
                    for hit in pack["hits"]:
                        single = score_ranges({"hits": [hit]}, refs, resolver.documents)
                        relevant_chunks += bool(single["retained_spans"] or single["retained_conditions"])
                        judged_chunks += 1
        except Exception as exc:
            errors += 1
            row.update(status="error", error_type=type(exc).__name__)
        row["latency_ms"] = round((time.perf_counter()-started)*1000, 2)
        rows.append(row)
    ratio = lambda a, b: round(a/b, 4) if b else None
    return {"metric_version": "evidence_budget_v1", "query_contract": QUERY_CONTRACT,
            "budget": asdict(budget), "cases": len(cases), "answerable_cases": positive,
            "supported_cases": positive-followup, "followup_cases": followup,
            "unanswerable_cases": negative, "urgent_cases": urgent, "error_cases": errors,
            "document_recall_at_budget": ratio(doc_recall, positive),
            "followup_document_recall_at_budget": ratio(followup_recall, followup),
            "evidence_labelled_cases": labelled,
            "evidence_span_recall_at_budget": ratio(totals["retained_spans"], totals["evidence_spans"]),
            "critical_condition_retention": ratio(totals["retained_conditions"], totals["critical_conditions"]),
            "labelled_context_chunk_precision": ratio(relevant_chunks, judged_chunks),
            "context_chunks_with_reference": relevant_chunks, "context_chunks_considered": judged_chunks,
            "candidate_union_document_recall": ratio(union_recall, union_count),
            "candidate_rerank_pool_document_recall": ratio(pool_recall, pool_count),
            "candidate_trace_cases": {"union": union_count, "rerank_pool": pool_count},
            "candidate_coverage_basis": "full_source_chunks_not_model_token_visibility",
            "unanswerable_rejection_rate": ratio(rejected, negative),
            "urgent_detection_rate": ratio(urgent_ok, urgent), **totals, "details": rows}
