"""Audit the predeclared stage-2 gates; never changes model/index settings."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from .chat import contextual_facts_query, clip_retrieval_query
from .experiment import MEDICAL, digest, load_suite, repository_version
from .knowledge_base import load_corpus
from .stage2_matrix import CONFIGURATIONS
from .token_budget import query_parts


METRICS = ("document_recall_at_budget", "evidence_span_recall_at_budget", "critical_condition_retention",
           "rerank_visible_span_recall", "rerank_visible_condition_retention", "unanswerable_rejection_rate",
           "error_cases", "rerank_execution_failures", "subsequent_search_p95_ms")


def row_scores(row):
    scores = {"document_recall": row.get("document_recall_at_budget"),
              "negative_rejection": float(row["rejected"]) if "rejected" in row else None,
              "candidate_union_recall": row.get("candidate_union_recall"),
              "candidate_pool_recall": row.get("candidate_rerank_pool_recall")}
    for prefix, field in (("final", "range_metrics"), ("model_visible", "rerank_visible_ranges")):
        ranges = row.get(field, {})
        for name, numerator, denominator in (("spans", "retained_spans", "evidence_spans"),
                                              ("conditions", "retained_conditions", "critical_conditions")):
            count = ranges.get(denominator, 0)
            scores[f"{prefix}_{name}"] = ranges.get(numerator, 0)/count if count else None
    return scores


def paired_changes(before, after):
    if [r["id"] for r in before] != [r["id"] for r in after]:
        raise ValueError("paired rows differ")
    result = {}
    for left, right in zip(before, after):
        a, b = row_scores(left), row_scores(right)
        for metric in a:
            row = result.setdefault(metric, {"wins": [], "losses": [], "ties": 0, "unmeasured": 0})
            if a[metric] is None or b[metric] is None:
                row["unmeasured"] += 1
            elif b[metric] > a[metric]+1e-8:
                row["wins"].append(left["id"])
            elif b[metric] < a[metric]-1e-8:
                row["losses"].append(left["id"])
            else:
                row["ties"] += 1
    return result


def audit_label_origins(groups, documents):
    manifest_path = MEDICAL.parents[1]/"medical-rag-data/registry/chinese_symptoms_20260928.json"
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if "headings are editorial" not in manifest["capture_method"]:
        raise ValueError("excerpt-origin declaration changed; reassess label origins")
    editorial_docs = {item["doc_id"] for item in manifest["documents"]}
    by_id = {d.doc_id: d for d in documents}
    flagged = []
    for group, cases in groups.items():
        for case in cases:
            for ref in case.get("expected_evidence", []):
                if ref["doc_id"] not in editorial_docs: continue
                doc = by_id[ref["doc_id"]]
                headings = [(m.start(), m.end()) for m in re.finditer(r"(?m)^#{1,6}[^\r\n]*", doc.body)]
                for field in ("ranges", "required_conditions"):
                    for a, b in ref.get(field, []):
                        if any(x <= a < b <= y for x, y in headings):
                            flagged.append({"group": group, "case": case["id"], "doc_id": doc.doc_id,
                                            "field": field, "range": [a, b], "origin": "editorial_scope_heading"})
    return {"scope": "known_editorial_heading_labels_not_full_raw_origin_verification",
            "manifest_sha256": hashlib.sha256(raw).hexdigest(), "flags": flagged,
            "condition_metric_caveat": "Canonical body retention includes these scope markers; do not call it literal raw-page medical support."}


def retained(text, spans, start=0, end=None):
    required = {i for i in range(start, len(text) if end is None else end) if not text[i].isspace()}
    covered = {i for a, b in spans for i in range(a, b)}
    return bool(required) and required.issubset(covered)


def gate_result(results, baseline, cases):
    evidence = results["evidence-regression"]["rerank"]
    rows = {r["id"]: r for r in evidence["details"]}
    probes = {}
    for identifier in ("EVS01", "EVS02", "EVS03"):
        row = rows[identifier]
        visible, final = row.get("rerank_visible_ranges", {}), row.get("range_metrics", {})
        probes[identifier] = {"model_input": bool(visible.get("evidence_spans")) and visible.get("evidence_spans") == visible.get("retained_spans"),
                              "final_pack": bool(final.get("evidence_spans")) and final.get("evidence_spans") == final.get("retained_spans")}
    doc_regressions, negative_regressions = [], []
    for group, modes in results.items():
        h, r = modes["hybrid"], modes["rerank"]
        if h["document_recall_at_budget"] is not None and r["document_recall_at_budget"] < h["document_recall_at_budget"]-1e-4:
            doc_regressions.append(group)
        before, after = baseline[group]["rerank"]["unanswerable_rejection_rate"], r["unanswerable_rejection_rate"]
        if before is not None and (after is None or after < before-1e-4): negative_regressions.append(group)
    query_checks = []
    by_case = {c["id"]: c for c in cases}
    for row in results["token-input-regression"]["rerank"]["details"]:
        if row["id"].startswith(("TKF", "TKT", "TKL")):
            case = by_case[row["id"]]
            query = clip_retrieval_query(contextual_facts_query(case["query"], case.get("history", "")))
            current, start, _, _ = query_parts(query)
            # For deliberately overlong current questions, require the final
            # 20 characters. Full current questions are required in normal
            # length follow-ups. This is an input check, not semantic judging.
            required_start = len(query)-20 if row["id"].startswith("TKL") else start
            inputs = row.get("rerank_inputs", [])
            query_checks.append({"id": row["id"], "passed": bool(inputs) and all(
                retained(query, trace["query_ranges"], required_start, start+len(current)) for trace in inputs)})
    hybrid = results["evidence-regression"]["hybrid"]
    gates = {
        "three_source_regressions_visible_and_retained": all(v["model_input"] and v["final_pack"] for v in probes.values()),
        "all_ten_labelled_conditions_retained": evidence["critical_conditions"] == evidence["retained_conditions"] == 10,
        "evidence_not_below_own_hybrid": all(evidence[m] is not None and evidence[m] >= hybrid[m]-1e-4
            for m in ("evidence_span_recall_at_budget", "critical_condition_retention")),
        "documents_not_below_own_hybrid_all_groups": not doc_regressions,
        "negative_filter_not_below_same_code_legacy256": not negative_regressions,
        "current_question_checks": bool(query_checks) and all(r["passed"] for r in query_checks),
    }
    return {"gates": gates, "input_and_regression_gates_passed": all(gates.values()), "three_probes": probes,
            "document_regression_groups": doc_regressions, "negative_regression_groups": negative_regressions,
            "query_checks": query_checks}


def compare(directory):
    matrix = json.loads((directory/"matrix.json").read_text(encoding="utf-8"))
    if not matrix["complete"]:
        raise ValueError("matrix is incomplete; keep failures and finish it before acceptance")
    reports, files = {}, {}
    for name in CONFIGURATIONS:
        attempt = matrix["attempts"][name][-1]
        path = (directory/attempt["output"]).resolve()
        if not path.is_relative_to(directory.resolve()): raise ValueError("report escaped matrix directory")
        raw = path.read_bytes()
        report = json.loads(raw)
        if not attempt["complete"] or not report["complete"]:
            raise ValueError("incomplete configuration")
        reports[name] = report
        files[name] = {"name": path.name, "sha256": hashlib.sha256(raw).hexdigest()}
    base = reports["legacy-256"]
    for name, report in reports.items():
        for field in ("code", "suite_manifest_sha256", "query_contract", "query_transport_contract", "metric_contract",
                      "selected_groups", "profiles", "k", "corpus_sha256", "parameters", "cpu_threads", "ranking_constants", "embedding", "packages"):
            if report[field] != base[field]: raise ValueError(f"comparison signature differs: {name}: {field}")
        if report["code"]["tracked_changes"]: raise ValueError("dirty implementation was used")
        for field in ("name", "weight_sha256", "batch_size", "tokenizer_sha256"):
            if report["reranker"][field] != base["reranker"][field]: raise ValueError("reranker assets differ")
        expected = CONFIGURATIONS[name]
        if any(report["input_settings"].get(k) != v for k, v in expected.items()): raise ValueError("configuration differs from predeclared matrix")
        if (report["reranker"]["max_length"] != expected["rerank_max_length"]
                or report["reranker"]["input_policy"] != expected["input_policy"]):
            raise ValueError("actual reranker settings differ from requested settings")
        for group, modes in report["results"].items():
            for profile, result in modes.items():
                if result["error_cases"] or result["rerank_execution_failures"]: raise ValueError("unverified model execution")
                if [r["id"] for r in result["details"]] != [r["id"] for r in base["results"][group][profile]["details"]]:
                    raise ValueError("different case order or denominator")
    suite, groups = load_suite(MEDICAL/"evaluation/suite_v5.json")
    if digest(suite) != matrix["signature"]["suite_sha256"]: raise ValueError("suite changed after experiment")
    decisions = {name: gate_result(report["results"], base["results"], groups["token-input-regression"])
                 for name, report in reports.items()}
    return {"scope": "stage2_exposed_engineering_not_independent_validation_or_answer_acceptance",
            "report_version": "stage2_comparison_v1",
            "complete": True, "model_runs_complete": True, "matrix_signature": matrix["signature"], "input_files": files,
            "analyzer": {"code": repository_version(), "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
            "gates_predeclared_in": "docs/rag-stage2-input-and-chunking.md@5849846",
            "label_origin_audit": audit_label_origins(groups, load_corpus(MEDICAL/"source_corpus")),
            "decisions": decisions, "online_ready": False,
            "remaining_release_gates": ["stage4_independent_validation_and_evidence_gate", "stage6_performance_and_atomic_index_rollback"],
            "metrics": {name: {group: {profile: {k: result.get(k) for k in METRICS}
                         for profile, result in modes.items()} for group, modes in report["results"].items()}
                        for name, report in reports.items()},
            "resources": {name: {"before": r["memory_before"], "after": r.get("memory_after"), "chunks": r["index_chunks"]}
                          for name, r in reports.items()},
            "paired_case_changes": {name: {group: {
                "versus_legacy256_rerank": paired_changes(base["results"][group]["rerank"]["details"], modes["rerank"]["details"]),
                "versus_own_hybrid": paired_changes(modes["hybrid"]["details"], modes["rerank"]["details"])}
                for group, modes in report["results"].items()} for name, report in reports.items()},
            "performance_scope": matrix["performance_scope"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.directory)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2); handle.write("\n")
    print(json.dumps({name: row["input_and_regression_gates_passed"] for name, row in report["decisions"].items()}))
