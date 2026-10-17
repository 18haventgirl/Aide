"""Reconstruct full recorded rerank-pool ranges without running a model.

Distinguishes candidate selection, encoder clipping and final packing losses.
It does not infer why a relevance filter rejected a passage.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .experiment import MEDICAL, digest, load_suite, repository_version
from .knowledge_base import load_corpus
from .schema import MedicalHit
from .source_provenance import SourceResolver
from .evaluation.metrics import score_ranges


def pool_pack(inputs, resolver, visible=False):
    rows, unknown = [], []
    for trace in inputs:
        key = (trace["doc_id"], trace["chunk_id"])
        binding, doc = resolver.bindings.get(key), resolver.documents.get(key[0])
        if isinstance(binding, list): binding = binding[0]  # Ranked child, not expanded context.
        if binding is None or doc is None:
            unknown.append(list(key)); continue
        hit = MedicalHit(chunk_id=key[1], doc_id=doc.doc_id, title=doc.title,
            section_path=binding.section_path, text=binding.text, source_org=doc.source_org,
            source_url=str(doc.source_url), source_sha256=doc.source_sha256,
            document_version=doc.version, usage_scope=doc.usage_scope)
        mapping = (resolver.resolve_intervals(hit, trace["passage_ranges"]) if visible
                   else resolver.resolve(hit, hit.text))
        if mapping["status"] == "unmapped":
            unknown.append(list(key)); continue
        rows.append({"doc_id": doc.doc_id, "source_mapping": mapping})
    return {"hits": rows}, unknown


def retained_label_ids(pack, references, documents):
    result = set()
    for ref in references:
        for field, numerator in (("ranges", "retained_spans"), ("required_conditions", "retained_conditions")):
            for i, span in enumerate(ref.get(field, [])):
                single = {**ref, "ranges": [span] if field == "ranges" else [],
                          "required_conditions": [span] if field == "required_conditions" else []}
                if score_ranges(pack, [single], documents)[numerator]:
                    result.add(f"{ref['doc_id']}:{field}:{i}")
    return result


def diagnose(directory):
    matrix = json.loads((directory/"matrix.json").read_text(encoding="utf-8"))
    if not matrix["complete"]: raise ValueError("finish the matrix before acceptance forensics")
    suite, groups = load_suite(MEDICAL/"evaluation/suite_v5.json")
    if digest(suite) != matrix["signature"]["suite_sha256"]:
        raise ValueError("suite changed after experiment")
    documents = load_corpus(MEDICAL/"source_corpus")
    if digest([d.model_dump(mode="json") for d in documents]) != matrix["signature"]["corpus_sha256"]:
        raise ValueError("source corpus changed after experiment")
    results = {}
    for name, attempts in matrix["attempts"].items():
        path = (directory/attempts[-1]["output"]).resolve()
        if not path.is_relative_to(directory.resolve()): raise ValueError("report escaped directory")
        raw = path.read_bytes(); report = json.loads(raw)
        if not report["complete"]: raise ValueError("incomplete input report")
        chunker = None
        if report["input_settings"]["chunk_strategy"] == "token-v1":
            from .token_chunking import TokenChunker
            chunker = TokenChunker.local(child_tokens=report["input_settings"]["child_tokens"])
            if chunker.config != {k: report["chunking"][k] for k in chunker.config}:
                raise ValueError("tokenizer/chunk configuration changed")
        resolver = SourceResolver(documents, chunker)
        rows = []
        for group, modes in report["results"].items():
            by_id = {c["id"]: c for c in groups[group]}
            for row in modes["rerank"]["details"]:
                refs = by_id[row["id"]].get("expected_evidence", [])
                if not refs: continue
                pack, unknown = pool_pack(row.get("rerank_inputs", []), resolver)
                visible_pack, visible_unknown = pool_pack(row.get("rerank_inputs", []), resolver, visible=True)
                full = score_ranges(pack, refs, resolver.documents)
                pool_ids = retained_label_ids(pack, refs, resolver.documents)
                visible_ids = retained_label_ids(visible_pack, refs, resolver.documents)
                final_ids = retained_label_ids(row.get("evidence_pack", {"hits": []}), refs, resolver.documents)
                rows.append({"id": row["id"], "group": group, "full_recorded_pool": full,
                    "actual_model_input": row.get("rerank_visible_ranges"), "final_pack": row.get("range_metrics"),
                    "unknown_recorded_chunks": unknown+visible_unknown, "input_trace_present": bool(row.get("rerank_inputs")),
                    "full_pool_label_ids": sorted(pool_ids), "visible_label_ids": sorted(visible_ids), "final_label_ids": sorted(final_ids),
                    "encoder_lost_label_ids": sorted(pool_ids-visible_ids), "final_lost_visible_label_ids": sorted(visible_ids-final_ids)})
        results[name] = {"input_report_sha256": hashlib.sha256(raw).hexdigest(), "details": rows,
            "unverified_trace_cases": [r["id"] for r in rows if not r["input_trace_present"] or r["unknown_recorded_chunks"]],
            "pool_missing_span_cases": [r["id"] for r in rows if r["input_trace_present"] and not r["unknown_recorded_chunks"]
                and r["full_recorded_pool"]["retained_spans"] < r["full_recorded_pool"]["evidence_spans"]],
            "encoder_lost_span_cases": [r["id"] for r in rows if any(":ranges:" in key for key in r["encoder_lost_label_ids"])],
            "final_lost_visible_span_cases": [r["id"] for r in rows if any(":ranges:" in key for key in r["final_lost_visible_label_ids"])]}
    return {"scope": "exact_source_range_forensics_not_semantic_or_clinical_judgement", "complete": True,
            "code": repository_version(), "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "matrix_signature": matrix["signature"], "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); report = diagnose(args.directory)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2); handle.write("\n")
    print(json.dumps({name: {k: v for k, v in r.items() if k not in {"details", "input_report_sha256"}}
                      for name, r in report["results"].items()}))
