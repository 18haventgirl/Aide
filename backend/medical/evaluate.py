"""Evaluate retrieval against labelled questions; no user chat data is read."""

import argparse
import json
import math
import time
from pathlib import Path

from .runtime import get_knowledge_base
from .chat import is_urgent, is_out_of_scope, contextual_query


def evaluate(kb, cases: list[dict], k: int = 3) -> dict:
    if not cases:
        raise ValueError("evaluation cases must not be empty")
    rows = []
    recall_1 = recall_k = reciprocal_rank = ndcg_k = 0.0
    forbidden_hits = forbidden_checks = 0
    retrieval_latencies: list[float] = []
    supported = unanswered = urgent = followup = 0
    correct_rejections = correct_urgent = 0
    followup_recall_k = 0.0
    for case in cases:
        kind = case.get("kind", "supported")
        if kind == "urgent":
            urgent += 1
            matched = is_urgent(case["query"])
            correct_urgent += matched
            rows.append({"id": case["id"], "kind": kind, "urgent_detected": matched})
            continue
        if kind not in {"supported", "unanswerable", "followup"}:
            raise ValueError(f"unknown case kind: {kind}")
        expected = set(case.get("expected_doc_ids", []))
        if kind in {"supported", "followup"} and not expected:
            raise ValueError(f"case {case['id']} has no expected documents")
        query = (contextual_query(case["query"], [{"role": "user", "content": case["history"]}])
                 if kind == "followup" else case["query"])
        search_started = time.perf_counter()
        retrieved = ([] if is_out_of_scope(query) else
                     list(dict.fromkeys(hit.doc_id for hit in kb.search(query, limit=20))))
        retrieval_latencies.append((time.perf_counter() - search_started) * 1000)
        if kind == "unanswerable":
            unanswered += 1
            correct_rejections += not retrieved
            rows.append({"id": case["id"], "kind": kind, "retrieved": retrieved[:k],
                         "rejected": not bool(retrieved)})
            continue
        rank = next((i for i, doc_id in enumerate(retrieved, 1) if doc_id in expected), None)
        forbidden = set(case.get("forbidden_doc_ids", []))
        if forbidden:
            forbidden_checks += 1
            forbidden_hits += bool(forbidden.intersection(retrieved[:k]))
        if kind == "followup":
            followup += 1
            followup_recall_k += bool(rank and rank <= k)
            rows.append({"id": case["id"], "kind": kind, "expected": sorted(expected),
                         "retrieved": retrieved[:k], "first_match_rank": rank})
            continue
        supported += 1
        recall_1 += bool(rank and rank <= 1)
        recall_k += bool(rank and rank <= k)
        reciprocal_rank += 1 / rank if rank else 0
        ndcg_k += (1 / math.log2(rank + 1)) if rank and rank <= k else 0
        rows.append({"id": case["id"], "kind": kind, "expected": sorted(expected),
                     "retrieved": retrieved[:k], "first_match_rank": rank,
                     "forbidden_retrieved": sorted(forbidden.intersection(retrieved[:k]))})
    sorted_latency = sorted(retrieval_latencies)
    p95_index = max(0, math.ceil(len(sorted_latency) * 0.95) - 1)
    return {
        "cases": len(cases), "supported_cases": supported,
        "unanswerable_cases": unanswered, "urgent_cases": urgent, "followup_cases": followup,
        "recall_at_1": round(recall_1 / supported, 3) if supported else None,
        f"recall_at_{k}": round(recall_k / supported, 3) if supported else None,
        "mrr": round(reciprocal_rank / supported, 3) if supported else None,
        f"ndcg_at_{k}": round(ndcg_k / supported, 3) if supported else None,
        f"forbidden_hit_rate_at_{k}": (round(forbidden_hits / forbidden_checks, 3)
                                       if forbidden_checks else None),
        "average_retrieval_latency_ms": (round(sum(retrieval_latencies) / len(retrieval_latencies), 1)
                                         if retrieval_latencies else None),
        "p95_retrieval_latency_ms": (round(sorted_latency[p95_index], 1)
                                     if sorted_latency else None),
        "unanswerable_rejection_rate": round(correct_rejections / unanswered, 3) if unanswered else None,
        "urgent_detection_rate": round(correct_urgent / urgent, 3) if urgent else None,
        f"followup_recall_at_{k}": round(followup_recall_k / followup, 3) if followup else None,
        "details": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Medical knowledge retrieval evaluation")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("eval_cases.json"))
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.k <= 20:
        parser.error("k must be between 1 and 20")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    print(json.dumps(evaluate(get_knowledge_base(args.preview), cases, args.k), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
