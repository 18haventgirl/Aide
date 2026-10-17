"""Tokenizer-only source coverage/length audit; NOT a model quality experiment.

Run in a fresh process with USE_TORCH=0 when RAM is constrained. Assets are
loaded locally; there are no network requests, model forwards or user writes.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .resource_budget import require_available, memory_status


def run(output):
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"scope": "tokenizer_only_not_model_quality", "complete": False,
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "stage": "preflight"}
    with output.open("x", encoding="utf-8") as handle: json.dump(report, handle)
    def save():
        temporary = output.with_suffix(output.suffix+".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        temporary.replace(output)
    try:
        report["memory_before"] = require_available(256)
        from .experiment import MEDICAL, digest, repository_version
        from .knowledge_base import load_corpus
        from .token_chunking import TokenChunker
        from .token_budget import PairBudget, prepare_pair
        from .chunking import chunk_document
        from .source_provenance import SourceResolver
        from .schema import MedicalHit
        documents = load_corpus(MEDICAL/"source_corpus")
        report.update(code=repository_version(), corpus_sha256=digest([d.model_dump(mode="json") for d in documents]),
                      documents=len(documents), candidates=[])
        # New offset instrumentation must not change the historical legacy
        # token IDs. Verify with the REAL local tokenizer at both lengths.
        probe = TokenChunker.local()
        parity_checked = 0
        questions = ["健康成年人每周活动多久？", "用户此前明确陈述："+"过去生活背景。"*100+"\n当前问题：哪些情况需要就医？",
                     "长问题前文。"*200+"水果可以替代蔬菜吗？"]
        for doc in documents:
            for chunk in chunk_document(doc.body, doc.title):
                text = f"{doc.title}\n{chunk.section_path}\n{chunk.text}"
                for length in (256, 512):
                    for query in questions:
                        actual, _ = prepare_pair(probe.tokenizer, query, text, PairBudget(max_length=length), "legacy")
                        expected = dict(probe.tokenizer(query, text, truncation=True, max_length=length))
                        if actual != expected:
                            raise ValueError("legacy token IDs changed under instrumentation")
                        parity_checked += 1
        report["real_tokenizer_legacy_parity"] = {"checked_pairs": parity_checked, "mismatches": 0}
        save()
        for size, length in ((180, 256), (220, 384)):
            report["stage"] = f"audit_child_{size}_pair_{length}"
            save()
            started = time.perf_counter()
            maker = TokenChunker.local(child_tokens=size)
            resolver = SourceResolver(documents, maker)
            rows, pairs, unmapped, wrong_offsets = [], [], 0, 0
            for doc in documents:
                chunks = maker.chunks(doc)
                for chunk in chunks:
                    hit = MedicalHit(chunk_id=chunk.chunk_id, doc_id=doc.doc_id, title=doc.title,
                                     section_path=chunk.section_path, text=chunk.context, source_org=doc.source_org,
                                     source_url=str(doc.source_url), source_sha256=doc.source_sha256,
                                     document_version=doc.version, usage_scope=doc.usage_scope)
                    mapping = resolver.resolve(hit, hit.text)
                    unmapped += mapping["status"] == "unmapped"
                    for text, segments in ((chunk.text, chunk.segments), (chunk.context, chunk.context_segments)):
                        wrong_offsets += sum(text[a:b] != doc.body[c:d] for a, b, c, d in segments)
                    inputs, trace = prepare_pair(maker.tokenizer,
                        "当前很长的问题，用来填满明确分配给当前问题的六十四个token预算。"*10,
                        chunk.text, PairBudget(max_length=length))
                    # Every source body character represented by a child must
                    # survive its model input. Prefix metadata is checked too,
                    # but is not counted as source body evidence.
                    ranges = trace["passage_ranges"]
                    required = {i for a, b, _, _ in chunk.segments for i in range(a, b) if not chunk.text[i].isspace()}
                    visible = {i for a, b in ranges for i in range(a, b)}
                    pairs.append({"pair_tokens": len(inputs["input_ids"]), "source_clipped": not required.issubset(visible)})
                    rows.append({"doc_id": doc.doc_id, "chunk_id": chunk.chunk_id, "kind": chunk.kind,
                                 "child_tokens": maker.count(chunk.text), "context_tokens": maker.count(chunk.context),
                                 "context_chars": len(chunk.context), "atomic_boundary_split": chunk.boundary_split,
                                 "context_limited": chunk.context_limited, "parent_id": chunk.parent_id})
            report["candidates"].append({"config": maker.config, "pair_max_length": length,
                "index_version": maker.version, "chunks": len(rows), "unmapped": unmapped,
                "wrong_source_offsets": wrong_offsets,
                "max_child_tokens": max(r["child_tokens"] for r in rows),
                "max_context_tokens": max(r["context_tokens"] for r in rows),
                "max_context_chars": max(r["context_chars"] for r in rows),
                "context_over_evidence_char_limit": sum(r["context_chars"] > 1600 for r in rows),
                "atomic_boundary_splits": sum(r["atomic_boundary_split"] for r in rows),
                "limited_contexts": sum(r["context_limited"] for r in rows),
                "max_actual_pair_tokens": max(r["pair_tokens"] for r in pairs),
                "children_with_source_clipped_in_pair": sum(r["source_clipped"] for r in pairs),
                "audit_ms": round((time.perf_counter()-started)*1000, 1), "details": rows})
            save()
            print(json.dumps({k: v for k, v in report["candidates"][-1].items() if k not in {"details", "config"}}), flush=True)
        report.update(complete=True, stage="finished", memory_after=memory_status())
        save()
    except Exception as exc:
        report.update(complete=False, failure_type=type(exc).__name__)
        save()
        raise
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
