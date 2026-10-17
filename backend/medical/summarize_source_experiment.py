"""Archive source-only experiment metrics and exact range failure forensics.

Reconstructs tokenized chunks without a neural forward pass. Full raw evidence
text stays in the local report; the archive contains IDs, hashes and ranges.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .diagnose_input_ranges import pool_pack, retained_label_ids
from .evaluation.metrics import score_ranges
from .experiment import digest, load_suite, prepare_origin_contract, repository_version
from .knowledge_base import load_corpus
from .source_origins import OriginResolver


def summarize(report_path, suite_path, snapshot):
    raw = report_path.read_bytes()
    report = json.loads(raw)
    if not report.get("complete") or report.get("metric_contract") != "source-evidence-v1":
        raise ValueError("requires a complete strict-source experiment")
    if hashlib.sha256(suite_path.read_bytes()).hexdigest() != report["suite_manifest_sha256"]:
        raise ValueError("suite file changed after experiment")
    manifest, groups = load_suite(suite_path)
    if manifest != report["suite"]:
        raise ValueError("suite manifest differs")
    if any(case.get("kind", "supported") not in {"supported", "followup"}
           for group in report["selected_groups"] for case in groups[group]):
        raise ValueError("this pilot forensic summary currently requires only positive cases")
    documents = load_corpus(snapshot/"corpus")
    if digest([d.model_dump(mode="json") for d in documents]) != report["corpus_sha256"]:
        raise ValueError("corpus changed after experiment")
    audit, origins = prepare_origin_contract("source-evidence-v1", snapshot, snapshot/"corpus", documents,
        [case for group in report["selected_groups"] for case in groups[group]])
    if audit["origins_sha256"] != report["source_origin_audit"]["origins_sha256"]:
        raise ValueError("origin manifests changed after experiment")
    chunker = None
    if report["input_settings"]["chunk_strategy"] == "token-v1":
        from .token_chunking import TokenChunker
        chunker = TokenChunker.local(child_tokens=report["input_settings"]["child_tokens"])
        if chunker.config != {key: report["chunking"][key] for key in chunker.config}:
            raise ValueError("chunking/tokenizer assets changed after experiment")
    from .experiment import ROOT
    resolver = OriginResolver(documents, origins, ROOT/"medical-rag-data/raw", chunker=chunker)
    output = {}
    for group, modes in report["results"].items():
        cases = {case["id"]: case for case in groups[group]}
        output[group] = {}
        for mode, result in modes.items():
            if [row["id"] for row in result["details"]] != [case["id"] for case in groups[group]]:
                raise ValueError("experiment case rows differ from declared group")
            rows = []
            for row in result["details"]:
                refs = cases[row["id"]].get("expected_evidence", [])
                final_pack = row.get("evidence_pack", {"hits": []})
                final = score_ranges(final_pack, refs, resolver.documents)
                if final != row.get("range_metrics"):
                    raise ValueError("recorded final range metrics differ")
                item = {"id": row["id"], "status": row["status"], "kind": row["kind"],
                    "expected_source_ids": row["expected"], "retrieved_source_ids": row["retrieved"],
                    "document_recall_at_budget": row["document_recall_at_budget"], "final_ranges": final,
                    "final_label_ids": sorted(retained_label_ids(final_pack, refs, resolver.documents)),
                    "gold": refs, "latency_ms": row["latency_ms"]}
                if mode == "rerank":
                    pool, unknown = pool_pack(row.get("rerank_inputs", []), resolver)
                    visible, visible_unknown = pool_pack(row.get("rerank_inputs", []), resolver, visible=True)
                    full_ids = retained_label_ids(pool, refs, resolver.documents)
                    visible_ids = retained_label_ids(visible, refs, resolver.documents)
                    final_ids = set(item["final_label_ids"])
                    actual = score_ranges(visible, refs, resolver.documents)
                    if actual != row.get("rerank_visible_ranges"):
                        raise ValueError("recorded model-visible range metrics differ")
                    item.update(full_recorded_pool=score_ranges(pool, refs, resolver.documents),
                        actual_model_input=actual, unknown_recorded_chunks=unknown+visible_unknown,
                        full_pool_label_ids=sorted(full_ids), visible_label_ids=sorted(visible_ids),
                        encoder_lost_label_ids=sorted(full_ids-visible_ids),
                        final_lost_visible_label_ids=sorted(visible_ids-final_ids),
                        unverified_input_trace=not row.get("rerank_inputs") or bool(unknown+visible_unknown))
                rows.append(item)
            output[group][mode] = {"metrics": {k: v for k, v in result.items() if k != "details"}, "details": rows,
                "final_missing_range_cases": [r["id"] for r in rows if r["final_ranges"]["retained_spans"] < r["final_ranges"]["evidence_spans"]]}
            if mode == "rerank":
                output[group][mode].update(
                    pool_missing_range_cases=[r["id"] for r in rows if r["full_recorded_pool"]["retained_spans"] < r["full_recorded_pool"]["evidence_spans"]],
                    encoder_lost_range_cases=[r["id"] for r in rows if any(":ranges:" in label for label in r["encoder_lost_label_ids"])],
                    final_lost_visible_range_cases=[r["id"] for r in rows if any(":ranges:" in label for label in r["final_lost_visible_label_ids"])],
                    unverified_trace_cases=[r["id"] for r in rows if r["unverified_input_trace"]])
    return {"schema_version": 1, "complete": True, "scope": "source_derived_development_pilot_not_independent_validation",
            "input_report": report_path.name, "input_report_sha256": hashlib.sha256(raw).hexdigest(),
            "experiment_code": report["code"], "analysis_code": repository_version(),
            "analysis_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "corpus_sha256": report["corpus_sha256"], "origins_sha256": audit["origins_sha256"],
            "metric_contract": report["metric_contract"], "suite_manifest_sha256": report["suite_manifest_sha256"],
            "input_settings": report["input_settings"], "index_chunks": report["index_chunks"],
            "embedding": report["embedding"], "reranker": report.get("reranker"), "packages": report["packages"],
            "memory_before": report["memory_before"], "memory_after": report["memory_after"],
            "results": output, "release_ready": False, "generation_api_calls": 0,
            "limitations": ["12 source-derived positive cases across two topics; no negative or independent validation estimates",
                "one pass per mode; latency is descriptive and excludes HTTP/LLM",
                "literal range coverage is not answer or clinical correctness",
                "source body remains in local data; archive contains coordinates and hashes"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.report, args.suite, args.snapshot)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({group: {mode: {k: v for k, v in row.items() if k not in {"metrics", "details"}}
                             for mode, row in modes.items()} for group, modes in result["results"].items()}))
