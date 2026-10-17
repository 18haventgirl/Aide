"""Versioned, isolated retrieval experiments. No user DB or generation API calls."""
import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
from contextlib import ExitStack
import time

from .evaluate import evaluate, validate_cases, QUERY_CONTRACT
from .knowledge_base import INDEX_VERSION, MedicalKnowledgeBase, load_corpus
from .evidence_contract import EvidenceBudget
from .evaluation.evidence import evaluate_evidence
from .evaluation.metrics import validate_references

ROOT = Path(__file__).resolve().parents[2]
MEDICAL = Path(__file__).resolve().parent
PROFILES = ("keyword", "dense", "hybrid", "rerank")
PARAMETERS = {
    "MEDICAL_RESEARCH_MAX_DISTANCE": "0.50",
    "MEDICAL_DENSE_CANDIDATES": "24",
    "MEDICAL_LEXICAL_CANDIDATES": "24",
    "MEDICAL_RERANK_CANDIDATES": "8",
    "MEDICAL_RERANK_RELATIVE_FLOOR": "0.35",
    "MEDICAL_RERANK_MIN_SCORE": "0.05",
    "MEDICAL_MAX_CHUNKS_PER_DOCUMENT": "2",
    "MEDICAL_LEXICAL_CACHE_TTL_SECONDS": "60",
}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def load_suite(path: Path) -> tuple[dict, dict]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("hash_scheme") != "canonical-json-v1" or not manifest.get("groups"):
        raise ValueError("unsupported or empty suite manifest")
    if manifest.get("query_contract", QUERY_CONTRACT) != QUERY_CONTRACT:
        raise ValueError("unsupported query contract")
    groups, names = {}, set()
    for entry in manifest["groups"]:
        name = entry["name"]
        if name in names or entry["purpose"] not in {"development", "regression", "topic_acceptance", "frozen"}:
            raise ValueError("invalid or duplicate evaluation group")
        names.add(name)
        source = (path.parent / entry["path"]).resolve()
        if not source.is_relative_to(MEDICAL):
            raise ValueError("case file must stay inside medical package")
        raw = source.read_bytes()
        cases = json.loads(raw)
        if digest(cases) != entry["sha256"]:
            raise ValueError(f"case hash mismatch: {name}")
        validate_cases(cases)
        if len(cases) != entry["count"]:
            raise ValueError(f"case count mismatch: {name}")
        groups[name] = cases
    date.fromisoformat(manifest["evaluation_date"])
    return manifest, groups


def validate_source_bindings(cases, documents):
    by_id = {document.doc_id: document for document in documents}
    for case in cases:
        if "source_binding" not in case:
            continue
        binding = case["source_binding"]
        required = {"doc_id", "version", "source_locator", "normalized_document_sha256"}
        if not isinstance(binding, dict) or not required.issubset(binding):
            raise ValueError(f"invalid source binding: {case['id']}")
        doc_id = binding["doc_id"]
        if not isinstance(doc_id, str):
            raise ValueError(f"invalid source binding: {case['id']}")
        if doc_id not in case.get("expected_doc_ids", []) or doc_id not in by_id:
            raise ValueError(f"invalid source binding: {case['id']}")
        document = by_id[doc_id]
        if (binding["version"] != document.version
                or binding["source_locator"] != document.source_locator
                or binding["normalized_document_sha256"] != digest(document.model_dump(mode="json"))):
            raise ValueError(f"frozen source changed: {case['id']}")


class KeywordBaseline:
    """Positive full-corpus BM25, no dense encoding or reranker threshold."""
    def __init__(self, kb):
        from .lexical import LexicalIndex
        self.kb = kb
        data = kb.collection.get(include=["documents", "metadatas"])
        self.index = LexicalIndex(data["ids"], data["documents"])
        self.rows = {cid: {"chunk_id": cid, "text": body, "metadata": meta,
                           "distance": None, "retrieval_method": "lexical"}
                     for cid, body, meta in zip(data["ids"], data["documents"], data["metadatas"])}
        self.metrics = {}

    def search(self, query, limit=20, today=None):
        ranked = self.index.ranked(query, len(self.rows))
        self._last_ranked = [cid for cid, _ in ranked
                             if self.kb._metadata_is_current(self.rows[cid]["metadata"], today or date.today())]
        counts, output, seen_contexts = Counter(), [], set()
        for cid, score in ranked:
            row = self.rows[cid]
            if not self.kb._metadata_is_current(row["metadata"], today or date.today()):
                continue
            doc_id = row["metadata"]["doc_id"]
            if counts[doc_id] >= int(PARAMETERS["MEDICAL_MAX_CHUNKS_PER_DOCUMENT"]):
                continue
            hit = self.kb._to_hit({**row, "lexical_score": score}, expand=True)
            if self.kb.chunker and (doc_id, hit.text) in seen_contexts:
                continue
            seen_contexts.add((doc_id, hit.text))
            counts[doc_id] += 1
            output.append(hit)
            if len(output) == limit:
                break
        self.metrics = {"candidate_count": len(ranked), "selected_count": len(output),
                        "reranker_status": "disabled", "baseline": "positive_bm25"}
        return output

    def search_metrics(self):
        return dict(self.metrics)

    def candidate_trace(self):
        return {"union": [self.kb._to_hit(self.rows[cid]) for cid in self._last_ranked]}


class DatedSearch:
    def __init__(self, searcher, day):
        self.searcher, self.day = searcher, day

    def search(self, query, limit=20):
        return self.searcher.search(query, limit=limit, today=self.day)

    def search_metrics(self):
        return self.searcher.search_metrics()

    def candidate_trace(self):
        return self.searcher.candidate_trace() if hasattr(self.searcher, "candidate_trace") else {}


def repository_version():
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    try:
        files = ["experiment.py", "evaluate.py", "knowledge_base.py", "chunking.py", "lexical.py",
                 "chat.py", "schema.py", "bge_embedding.py", "bge_reranker.py",
                 "evidence_contract.py", "source_provenance.py", "evaluation/evidence.py", "evaluation/metrics.py"]
        files += ["token_budget.py", "token_chunking.py"]
        return {"commit": git("rev-parse", "HEAD"),
                "retrieval_implementation_sha256": digest({name: hashlib.sha256((MEDICAL/name).read_bytes()).hexdigest() for name in files}),
                "tracked_changes": bool(git("status", "--porcelain", "--untracked-files=no"))}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "tracked_changes": None}


def mode_comparisons(results, k):
    comparisons = []
    for group, modes in results.items():
        for base, other in (("keyword", "dense"), ("dense", "hybrid"), ("hybrid", "rerank")):
            if base not in modes or other not in modes:
                continue
            metrics = {}
            for key in (f"recall_at_{k}", f"mrr_at_{k}", f"ndcg_at_{k}", "unanswerable_rejection_rate",
                        "document_recall_at_budget", "evidence_span_recall_at_budget", "critical_condition_retention"):
                left, right = modes[base].get(key), modes[other].get(key)
                if left is not None and right is not None:
                    metrics[key] = round(right-left, 4)
            comparisons.append({"group": group, "baseline": base, "candidate": other, "deltas": metrics})
    return comparisons


def run_experiment(manifest_path, corpus_path, output, groups=None, profiles=PROFILES, k=5,
                   metric_contract="evidence-v1", *, rerank_max_length=256, input_policy="legacy",
                   chunk_strategy="legacy", child_tokens=180):
    output.parent.mkdir(parents=True, exist_ok=True)
    initial = {"report_version": "retrieval_experiment_v2", "complete": False,
               "stage": "preflight", "started_at_utc": datetime.now(timezone.utc).isoformat(),
               "requested": {"suite": str(manifest_path), "groups": groups, "profiles": list(profiles), "k": k,
                             "metric_contract": metric_contract, "rerank_max_length": rerank_max_length,
                             "input_policy": input_policy, "chunk_strategy": chunk_strategy, "child_tokens": child_tokens}}
    # Exclusive reservation protects historical runs, including concurrent writers.
    with output.open("x", encoding="utf-8") as handle:
        json.dump(initial, handle)
    try:
        return _run_experiment(manifest_path, corpus_path, output, groups, profiles, k, metric_contract,
                               rerank_max_length, input_policy, chunk_strategy, child_tokens)
    except Exception as exc:
        current = json.loads(output.read_text(encoding="utf-8"))
        current.update(complete=False, failure_type=type(exc).__name__)
        output.write_text(json.dumps(current, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        raise


def _run_experiment(manifest_path, corpus_path, output, groups, profiles, k, metric_contract,
                    rerank_max_length, input_policy, chunk_strategy, child_tokens):
    from .token_budget import POLICIES
    if (type(rerank_max_length) is not int or not 64 <= rerank_max_length <= 512
            or input_policy not in POLICIES or chunk_strategy not in {"legacy", "token-v1"}
            or type(child_tokens) is not int or not 64 <= child_tokens <= 220):
        raise ValueError("invalid experimental token settings")
    if chunk_strategy == "token-v1" and input_policy != "query_first_v1":
        raise ValueError("token chunks require explicit query/passage budgets")
    if metric_contract not in {"evidence-v1", "legacy-doc-v3"}:
        raise ValueError("unknown metric contract")
    manifest, cases_by_group = load_suite(manifest_path)
    selected = groups or list(cases_by_group)
    if not selected or set(selected) - set(cases_by_group) or len(set(selected)) != len(selected):
        raise ValueError("unknown, duplicate or empty group selection")
    if not profiles or set(profiles) - set(PROFILES) or len(set(profiles)) != len(profiles):
        raise ValueError("invalid profile selection")
    if not 1 <= k <= 20:
        raise ValueError("k must be between 1 and 20")
    budget = EvidenceBudget(max_chunks=k) if metric_contract == "evidence-v1" else None
    documents = load_corpus(corpus_path)
    for group in selected:
        validate_source_bindings(cases_by_group[group], documents)
        validate_references(cases_by_group[group], documents)
    day = date.fromisoformat(manifest["evaluation_date"])
    eligible = {d.doc_id for d in documents if d.is_searchable(day, research_mode=True)}
    unavailable = {}
    for entry in manifest["groups"]:
        if entry["name"] not in selected:
            continue
        missing = {did for c in cases_by_group[entry["name"]] for did in c.get("expected_doc_ids", [])} - eligible
        if missing and not entry.get("allow_historical_missing_ids", False):
            raise ValueError(f"unknown/ineligible expected docs: {entry['name']}: {sorted(missing)}")
        unavailable[entry["name"]] = sorted(missing)
    from .resource_budget import require_available, memory_status
    before = require_available(1536)
    previous = {key: os.environ.get(key) for key in PARAMETERS}
    report = {
        "report_version": "retrieval_experiment_v2", "scope": "developer_cases_not_blind_not_clinical",
        "stage": "model_and_index_initialization", "metric_contract": metric_contract,
        "started_at_utc": datetime.now(timezone.utc).isoformat(), "code": repository_version(),
        "suite": manifest, "suite_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "query_contract": QUERY_CONTRACT,
        "query_transport_contract": "current_question_first_charcap_v1",
        "selected_groups": selected, "profiles": list(profiles), "k": k,
        "corpus_sha256": digest([d.model_dump(mode="json") for d in documents]),
        "corpus_documents": len(documents), "eligible_documents": len(eligible),
        "unavailable_expected_doc_ids": unavailable, "index_version": INDEX_VERSION,
        "parameters": PARAMETERS, "cpu_threads": 2, "memory_before": before,
        "input_settings": {"rerank_max_length": rerank_max_length, "input_policy": input_policy,
                           "chunk_strategy": chunk_strategy, "child_tokens": child_tokens if chunk_strategy == "token-v1" else None},
        "ranking_constants": {"rrf_k": 60, "dense_weight": .6, "lexical_weight": .4,
                              "rerank_pool_dense_quota": 5, "rerank_pool_lexical_quota": 3},
        "metric_definitions": {"mrr": "first relevant document within top K only",
            "recall": "retrieved relevant document IDs / all labelled relevant IDs",
            "keyword": "positive full-corpus BM25; per-doc cap; no semantic rejection threshold",
            "latency": "service function, no HTTP/LLM; first search per mode separately reported"},
        "results": {name: {} for name in selected}, "complete": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        temporary.replace(output)
    try:
        save()
        os.environ.update(PARAMETERS)
        import torch
        import chromadb
        from chromadb.config import Settings
        from .bge_embedding import BGEEmbedding
        from .bge_reranker import BGEReranker
        torch.set_num_threads(2)
        started = time.perf_counter()
        embedding = BGEEmbedding(batch_size=4, query_input_policy=input_policy)
        report["embedding"] = {"name": embedding.name(), "weight_sha256": embedding.weight_sha256,
                               "batch_size": 4, "dimensions": 512}
        report["packages"] = {p: importlib.metadata.version(p) for p in ("torch", "transformers", "chromadb", "jieba")}
        with ExitStack() as cleanup:
            # In-memory Chroma belongs only to this CLI process. Do not open the
            # application's persistent path; Windows keeps persistent files open.
            client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
            if client.list_collections():
                raise ValueError("experiment requires a fresh isolated Chroma process")
            chunker = None
            if chunk_strategy == "token-v1":
                from .token_chunking import TokenChunker
                chunker = TokenChunker.local(child_tokens=child_tokens)
                report["chunking"] = {**chunker.config, "index_version": chunker.version}
            kb = MedicalKnowledgeBase(client, embedding, embedding.name(), research_mode=True, chunker=chunker)
            report["index_version"] = kb.index_version
            cleanup.callback(client.delete_collection, kb.collection.name)
            report["index_sync"] = kb.sync(documents, today=day)
            report["index_chunks"] = kb.collection.count()
            from .source_provenance import SourceResolver
            resolver = SourceResolver(documents, chunker=chunker)
            report["index_build_and_embedding_load_ms"] = round((time.perf_counter()-started)*1000, 1)
            keyword = KeywordBaseline(kb)
            for profile in profiles:
                report["stage"] = f"prepare_profile:{profile}"
                save()
                kb.use_lexical = profile in {"hybrid", "rerank"}
                kb.reranker = None
                kb.reranker_requested = profile == "rerank"
                if profile == "rerank":
                    require_available(1536)
                    model = BGEReranker(batch_size=1, max_length=rerank_max_length, input_policy=input_policy)
                    started = time.perf_counter()
                    model._load()
                    report["reranker"] = {"name": model.name(), "weight_sha256": model.weight_sha256,
                                          "load_ms": round((time.perf_counter()-started)*1000, 1),
                                          "max_length": rerank_max_length, "batch_size": 1,
                                          "input_policy": input_policy, "tokenizer_sha256": model.tokenizer_sha256}
                    kb.reranker = model
                for name in selected:
                    report["stage"] = f"evaluate:{profile}:{name}"
                    save()
                    searcher = DatedSearch(keyword if profile == "keyword" else kb, day)
                    result = (evaluate_evidence(searcher, cases_by_group[name], documents, budget, resolver,
                                                measure_rerank_visibility=profile == "rerank")
                              if budget else evaluate(searcher, cases_by_group[name], k))
                    timings = [r["latency_ms"] for r in result["details"] if "latency_ms" in r
                               and (not budget or ("evidence_pack" in r and not r.get("scope_gated")))]
                    warm = sorted(timings[1:])
                    result["first_search_ms"] = timings[0] if timings else None
                    result["subsequent_search_p95_ms"] = warm[math.ceil(.95*len(warm))-1] if warm else None
                    result["reranker_status_counts"] = dict(Counter(r.get("diagnostics", {}).get("reranker_status", "not_searched") for r in result["details"]))
                    result["rerank_execution_failures"] = (sum(
                        count for status, count in result["reranker_status_counts"].items()
                        if status not in {"applied", "not_searched"}) if profile == "rerank" else 0)
                    report["results"][name][profile] = result
                    report["memory_after"] = memory_status()
                    save()
                    print(json.dumps({"group": name, "profile": profile,
                        "document_recall": result.get("document_recall_at_budget", result.get(f"recall_at_{k}")),
                        "evidence_span_recall": result.get("evidence_span_recall_at_budget"),
                        "reranker_status": result["reranker_status_counts"]}), flush=True)
            report["comparisons"] = mode_comparisons(report["results"], k)
            report["evaluation_error_cases"] = sum(r.get("error_cases", 0) for modes in report["results"].values() for r in modes.values())
            report["rerank_execution_failures"] = sum(r["rerank_execution_failures"] for modes in report["results"].values() for r in modes.values())
            report["complete"] = report["evaluation_error_cases"] == report["rerank_execution_failures"] == 0
            report["stage"] = "finished"
            save()
    except Exception as exc:
        report["complete"] = False
        report["failure_type"] = type(exc).__name__
        save()
        raise
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=MEDICAL / "evaluation" / "suite_v4.json")
    parser.add_argument("--corpus", type=Path, default=MEDICAL / "source_corpus")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--group", action="append")
    parser.add_argument("--profiles", nargs="+", choices=PROFILES, default=list(PROFILES))
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--metric-contract", choices=("evidence-v1", "legacy-doc-v3"), default="evidence-v1")
    parser.add_argument("--rerank-max-length", type=int, default=256)
    parser.add_argument("--input-policy", choices=("legacy", "query_first_v1"), default="legacy")
    parser.add_argument("--chunk-strategy", choices=("legacy", "token-v1"), default="legacy")
    parser.add_argument("--child-tokens", type=int, default=180)
    args = parser.parse_args()
    run_experiment(args.suite, args.corpus, args.output, args.group, args.profiles, args.k, args.metric_contract,
                   rerank_max_length=args.rerank_max_length, input_policy=args.input_policy,
                   chunk_strategy=args.chunk_strategy, child_tokens=args.child_tokens)


if __name__ == "__main__":
    main()
