"""Audit exposed development labels and screen negative cases for lexical overlap."""
import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path

from ..experiment import digest, load_suite, prepare_origin_contract, repository_version, validate_source_bindings
from ..knowledge_base import load_corpus
from .partitioning import normalized_query


def development_preflight(suite_path, snapshot, history_suites=()):
    declaration = json.loads(suite_path.read_text(encoding="utf-8"))
    if any(group.get("purpose") not in {"development", "regression"} for group in declaration["groups"]):
        raise ValueError("preflight accepts exposed development and regression groups only")
    manifest, groups = load_suite(suite_path)
    if manifest.get("metric_contract") != "source-evidence-v1":
        raise ValueError("development source preflight requires the literal source contract")
    cases = [case for rows in groups.values() for case in rows]
    if any(c.get("split") != "development" or c.get("exposed_for_changes") is not True for c in cases):
        raise ValueError("each case must be explicitly exposed development data")
    if len({c["id"] for c in cases}) != len(cases) or len({normalized_query(c) for c in cases}) != len(cases):
        raise ValueError("duplicate ID or effective question in development suite")
    documents = load_corpus(snapshot/"corpus")
    validate_source_bindings(cases, documents)
    audit, _ = prepare_origin_contract("source-evidence-v1", snapshot, snapshot/"corpus", documents, cases)
    day = date.fromisoformat(manifest["evaluation_date"])
    eligible = {d.doc_id: d for d in documents if d.is_searchable(day, research_mode=True)}
    for case in cases:
        labelled = set(case.get("expected_doc_ids", [])) | set(case.get("forbidden_doc_ids", []))
        if not labelled.issubset(eligible):
            raise ValueError(f"unknown or ineligible source in {case['id']}")
        if case["kind"] == "unanswerable" and (not case.get("no_evidence_reason", "").strip() or not case.get("forbidden_doc_ids")):
            raise ValueError(f"hard negative requires a scope reason and a named distractor: {case['id']}")

    history = []
    for path in history_suites:
        header = json.loads(path.read_text(encoding="utf-8"))
        if any(group.get("purpose") == "validation" for group in header["groups"]):
            raise ValueError("held-out suites cannot be used as development exposure inputs")
        _, prior_groups = load_suite(path)
        prior = [c for rows in prior_groups.values() for c in rows]
        old_ids = {c["id"] for c in prior}
        old_inputs = {normalized_query(c) for c in prior}
        history.append({"suite_id": header["suite_id"], "suite_sha256": digest(header), "cases": len(prior),
                        "matching_ids": sorted(c["id"] for c in cases if c["id"] in old_ids),
                        "matching_normalized_inputs": sorted(c["id"] for c in cases if normalized_query(c) in old_inputs)})

    # Document-level BM25 here measures whether a tempting source shares the
    # question's words. It does not execute chunk retrieval or measure rejection.
    from ..lexical import LexicalIndex
    negatives = [c for c in cases if c["kind"] == "unanswerable"]
    screen = []
    if negatives:
        index = LexicalIndex(list(eligible), [d.title+"\n"+d.body for d in eligible.values()])
        for c in negatives:
            ranked = [doc_id for doc_id, _ in index.ranked(c["query"], len(eligible))]
            labelled = set(c["forbidden_doc_ids"])
            rank = next((i for i, doc_id in enumerate(ranked, 1) if doc_id in labelled), None)
            screen.append({"id": c["id"], "labelled_distractors": sorted(labelled),
                           "first_distractor_rank": rank, "first_three_docs": ranked[:3]})
    return {"schema_version": 1, "complete": True, "as_of": day.isoformat(),
            "scope": "development_source_labels_and_document_bm25_overlap",
            "code": repository_version(), "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "suite_id": manifest["suite_id"], "suite_file_sha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
            "snapshot": audit["snapshot"], "corpus_sha256": audit["corpus_sha256"], "origins_sha256": audit["origins_sha256"],
            "documents": len(documents), "eligible_documents": len(eligible), "origin_verified_documents": audit["origin_verified_documents"],
            "counts": dict(Counter(c["kind"] for c in cases)), "cases": len(cases),
            "groups": {name: len(rows) for name, rows in groups.items()},
            "literal_gold_spans": sum(len(ref["ranges"]) for c in cases for ref in c.get("expected_evidence", [])),
            "literal_conditions": sum(len(ref.get("required_conditions", [])) for c in cases for ref in c.get("expected_evidence", [])),
            "historical_exact_overlap_checks": history, "document_lexical_screen": screen,
            "distractor_in_first_three": sum(r["first_distractor_rank"] in (1, 2, 3) for r in screen),
            "neural_retrieval_executed": False, "llm_generation_calls": 0, "independent_validation_cases": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--history-suite", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = development_preflight(args.suite, args.snapshot, args.history_suite)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({key: report[key] for key in ("complete", "cases", "counts", "literal_gold_spans", "distractor_in_first_three")}, ensure_ascii=False))
