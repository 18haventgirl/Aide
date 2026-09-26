"""Two-process, reproducible development evaluation; does not publish candidates."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import time

from .huatuo_lite import DEFAULT_ROOT, digest, write_report
from .huatuo_pilot_index import index_directory, rows, sample_path
from .pilot_retrieval import PilotRetriever, rerank
from .resource_budget import memory_status, require_available

CASES = Path(__file__).with_name("eval_cases_huatuo_v1.json")


def metrics(results: list[dict], mode: str, k: int = 5) -> dict:
    recalls, reciprocal, ndcgs = [], [], []
    for row in results:
        expected = set(row["expected_ids"])
        retrieved = list(dict.fromkeys(r["id"] for r in row[mode]))
        matched = expected.intersection(retrieved[:k])
        recalls.append(len(matched)/len(expected))
        rank = next((i for i, rid in enumerate(retrieved, 1) if rid in expected), None)
        reciprocal.append(1/rank if rank and rank <= k else 0)
        dcg = sum(1/math.log2(i+2) for i, rid in enumerate(retrieved[:k]) if rid in expected)
        ideal = sum(1/math.log2(i+2) for i in range(min(k, len(expected))))
        ndcgs.append(dcg/ideal)
    return {"recall_at_5": round(sum(recalls)/len(recalls), 4),
            "mrr_at_5": round(sum(reciprocal)/len(reciprocal), 4),
            "ndcg_at_5": round(sum(ndcgs)/len(ndcgs), 4)}


def collect(root=DEFAULT_ROOT, limit=5000, cases_path=CASES):
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    ids = {r["id"] for r in rows(sample_path(root, limit))}
    if not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("empty or duplicate evaluation cases")
    for case in cases:
        if not case["expected_ids"] or not set(case["expected_ids"]) <= ids:
            raise ValueError(f"missing relevance reference: {case['id']}")
    retriever = PilotRetriever(root, limit)
    results = []
    for case in cases:
        results.append({**case, **retriever.retrieve(case["query"])})
        print(f"retrieved {len(results)}/{len(cases)}", flush=True)
    report = {"sample_sha256": retriever.sample_sha256, "cases_sha256": digest(cases_path),
              "evaluation_scope": "agent_authored_paraphrase_development_set_not_independent_or_clinical",
              "answer_eligible": False, "results": results, "memory": memory_status()}
    write_report(index_directory(root, limit) / "eval_candidates.json", report)
    return {"cases": len(results), "dense": metrics(results, "dense"), "hybrid": metrics(results, "hybrid")}


def score(root=DEFAULT_ROOT, limit=5000, cases_path=CASES):
    # Separate process releases the embedding model before loading cross encoder.
    require_available(2304)
    target = index_directory(root, limit)
    report = json.loads((target / "eval_candidates.json").read_text(encoding="utf-8"))
    if report["sample_sha256"] != digest(sample_path(root, limit)) or report["cases_sha256"] != digest(cases_path):
        raise ValueError("evaluation inputs changed; recollect candidates")
    import torch
    torch.set_num_threads(2)
    from .bge_reranker import BGEReranker
    model = BGEReranker(batch_size=1, max_length=512)
    statuses = Counter()
    for i, case in enumerate(report["results"], 1):
        require_available(512)
        started = time.perf_counter()
        case["reranked"], case["reranker_status"] = rerank(case["query"], case["hybrid"][:12], model)
        case["rerank_ms"] = round((time.perf_counter()-started)*1000, 1)
        statuses[case["reranker_status"]] += 1
        print(f"reranked {i}/{len(report['results'])}: {case['reranker_status']}", flush=True)
    summary = {"cases": len(report["results"]), "sample_sha256": report["sample_sha256"],
               "cases_sha256": report["cases_sha256"], "evaluation_scope": report["evaluation_scope"],
               "answer_eligible": False, "reranker_statuses": dict(statuses), "memory": memory_status(),
               "metrics": {mode: metrics(report["results"], mode) for mode in ("dense", "hybrid", "reranked")}}
    report["summary"] = summary
    write_report(target / "eval_results.json", report)
    write_report(target / "eval_summary.json", summary)
    return summary


def audit(root=DEFAULT_ROOT, limit=5000):
    records = list(rows(sample_path(root, limit)))
    missing = sum(not row.get("original_medical_source_url") for row in records)
    report = {"sample_sha256": digest(sample_path(root, limit)), "records": len(records),
              "missing_original_source": missing, "verified_for_answer": sum(r.get("answer_eligible") is True for r in records),
              "promotion_allowed": False, "decision": "query_research_only",
              "reason": "Original medical sources absent; automatic relevance scores do not validate medical statements.",
              "spot_check_ids": ["HTL-13485745", "HTL-8868029", "HTL-17595185", "HTL-16311935"]}
    write_report(index_directory(root, limit) / "quality_audit.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["collect", "score", "audit"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()
    result = {"collect": collect, "score": score, "audit": audit}[args.command](args.root, args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
