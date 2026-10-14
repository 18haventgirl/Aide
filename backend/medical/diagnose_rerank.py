"""Isolated forensic probe. Diagnostic examples do not select production parameters."""
import argparse
from collections import defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
import statistics
import time

from .experiment import MEDICAL, PARAMETERS, digest, load_suite, repository_version
from .knowledge_base import MedicalKnowledgeBase, load_corpus
from .resource_budget import require_available, memory_status

PROBE_IDS = ("CGS024", "CGS035", "CGS042", "CGS023", "CGS034", "CGS041", "CGN01", "CGN05")
ANCHORS = {"CGS024": "安装防鼠门", "CGS035": "在工作期间全程", "CGS042": "果汁不能代替水果"}


def run(output: Path):
    if output.exists():
        raise ValueError("refusing to overwrite diagnostic evidence")
    before = require_available(1536)
    manifest, groups = load_suite(MEDICAL / "evaluation/suite_v3.json")
    by_id = {c["id"]: c for c in groups["chinese-general-regression"]}
    report = {"scope": "forensic_selected_regression_not_new_quality_benchmark",
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "code": repository_version(), "suite": manifest["suite_id"],
              "dataset_sha256": digest(groups["chinese-general-regression"]),
              "probe_ids": PROBE_IDS, "cpu_threads": 2, "memory_before": before,
              "queries": [], "gold_variants": [], "batch_benchmark": [], "complete": False}
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        temporary.replace(output)

    import os
    previous = {k: os.environ.get(k) for k in PARAMETERS}
    os.environ.update(PARAMETERS)
    try:
        import torch, chromadb
        from chromadb.config import Settings
        from .bge_embedding import BGEEmbedding
        from .bge_reranker import BGEReranker
        torch.set_num_threads(2)
        documents = load_corpus(MEDICAL / "source_corpus")
        report["corpus_sha256"] = digest([d.model_dump(mode="json") for d in documents])
        embedding = BGEEmbedding(batch_size=4)
        model = BGEReranker(batch_size=1, max_length=256)
        model._load()
        report["model"] = {"name": model.name(), "weight_sha256": model.weight_sha256}
        client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
        if client.list_collections():
            raise ValueError("fresh process required")
        kb = MedicalKnowledgeBase(client, embedding, embedding.name(), research_mode=True, reranker=model)
        day = date.fromisoformat(manifest["evaluation_date"])
        report["index"] = kb.sync(documents, today=day)
        source = kb.collection.get(include=["documents", "metadatas"])
        text_rows = defaultdict(list)
        for cid, body, meta in zip(source["ids"], source["documents"], source["metadatas"]):
            text_rows[body].append({"chunk_id": cid, "doc_id": meta["doc_id"], "chunk_index": meta["chunk_index"]})

        class Recorder:
            def name(self): return model.name()
            def score(self, query, passages):
                self.passages = passages
                self.scores = model.score(query, passages)
                return self.scores

        recorder = Recorder()
        kb.reranker = recorder
        model.score("日常健康知识", ["一般健康知识与规律作息。"])
        pools = {}
        for cid in PROBE_IDS:
            case = by_id[cid]
            hits = kb.search(case["query"], limit=5, today=day)
            candidates = []
            for passage, score in zip(recorder.passages, recorder.scores):
                tokens = model._tokenizer(case["query"], passage, truncation=False, return_offsets_mapping=True)
                row = {"sources": text_rows[passage], "score_256": score,
                       "pair_tokens": len(tokens["input_ids"]), "truncated_256": len(tokens["input_ids"]) > 256}
                if cid in ANCHORS and any(r["doc_id"] in case.get("expected_doc_ids", []) for r in text_rows[passage]):
                    anchor_at = passage.find(ANCHORS[cid])
                    sequence = tokens.sequence_ids()
                    positions = [i for i, (sid, offset) in enumerate(zip(sequence, tokens["offset_mapping"]))
                                 if sid == 1 and anchor_at >= 0 and offset[0] <= anchor_at < offset[1]]
                    row.update(anchor=ANCHORS[cid], anchor_character=anchor_at,
                               anchor_pair_token=positions[0] if positions else None)
                candidates.append(row)
            row = {"id": cid, "expected": case.get("expected_doc_ids", []), "candidates": candidates,
                   "returned_docs": list(dict.fromkeys(h.doc_id for h in hits)), "metrics": kb.search_metrics()}
            report["queries"].append(row)
            pools[cid] = recorder.passages.copy()
            save()
            print(json.dumps({"id": cid, "gold_in_rerank_pool": any(set(r["doc_id"] for r in c["sources"]) & set(row["expected"]) for c in candidates), "returned_docs": row["returned_docs"]}), flush=True)

        # Only compare representations of the same relevant source. No thresholds
        # are selected on these already exposed regression cases.
        for cid, anchor in ANCHORS.items():
            case = by_id[cid]
            gold = [text for text in pools[cid] if anchor in text and any(
                r["doc_id"] in case["expected_doc_ids"] for r in text_rows[text])]
            if not gold:
                report["gold_variants"].append({"id": cid, "gold_anchor_missing_from_pool": True})
                continue
            passage = gold[0]
            model.max_length = 256
            score256 = model.score(case["query"], [passage])[0]
            require_available(1024)
            model.max_length = 512
            score512 = model.score(case["query"], [passage])[0]
            start = max(0, passage.index(anchor) - 55)
            span = passage[start:passage.index(anchor) + 100]
            title = passage.splitlines()[0]
            model.max_length = 256
            compact = title + "\n" + span
            compact_score = model.score(case["query"], [compact])[0]
            row = {"id": cid, "original_256_score": score256, "original_512_score": score512,
                   "diagnostic_compact_score": compact_score,
                   "compact_pair_tokens": len(model._tokenizer(case["query"], compact)["input_ids"]),
                   "compact_character_range": [start, passage.index(anchor)+100],
                   "compact_is_manual_gold_span_not_automatic_strategy": True}
            report["gold_variants"].append(row)
            save()
            print(json.dumps(row), flush=True)

        # Same fixed eight passages, three repeated warm runs each. Serial only;
        # no extrapolation to concurrent traffic or end-to-end answer latency.
        question = by_id["CGS024"]["query"]
        passages = pools["CGS024"]
        model.max_length = 256
        reference = None
        for batch in (1, 4, 8):
            require_available(1024)
            model.batch_size = batch
            values, deltas = [], []
            for _ in range(3):
                started = time.perf_counter()
                scores = model.score(question, passages)
                values.append(round((time.perf_counter()-started)*1000, 2))
                if reference is None: reference = scores
                deltas.append(max(abs(a-b) for a,b in zip(reference,scores)))
            row = {"batch_size": batch, "pairs": len(passages), "max_length": 256,
                   "warm_ms": values, "median_ms": statistics.median(values),
                   "maximum_score_delta_from_batch1": max(deltas)}
            report["batch_benchmark"].append(row)
            save()
            print(json.dumps(row), flush=True)
        report["memory_after"] = memory_status()
        report["complete"] = True
        save()
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
        save()
        raise
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__": main()
