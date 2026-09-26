"""Offline candidate retrieval. Never imported by the Medical Agent.

All returned records are unverified research candidates, irrespective of score.
Indexes must describe the same pinned sample and embedding model.
"""
from __future__ import annotations

from contextlib import closing
import argparse
import json
import math
from pathlib import Path
import sqlite3
import time

from .huatuo_lite import DEFAULT_ROOT, digest
from .huatuo_pilot_index import index_directory, lexical_search, rows, sample_path


def fuse(dense: list[dict], lexical: list[dict]) -> list[dict]:
    candidates = {}
    for channel, weight, hits in (("dense", 0.6, dense), ("lexical", 0.4, lexical)):
        seen = set()
        for rank, hit in enumerate(hits, 1):
            if hit["id"] in seen:
                continue
            seen.add(hit["id"])
            row = candidates.setdefault(hit["id"], dict(hit, fusion_score=0.0, answer_eligible=False))
            row[channel + "_rank"] = rank
            row["fusion_score"] += weight / (60 + rank)
    return sorted(candidates.values(), key=lambda row: (-row["fusion_score"], row["id"]))


def rerank(query: str, candidates: list[dict], model) -> tuple[list[dict], str]:
    """Return an intact RRF fallback on optional scorer failure."""
    if not candidates:
        return [], "empty"
    try:
        scores = model.score(query, [r["question"] + "\n" + r["answer"] for r in candidates])
        if len(scores) != len(candidates) or any(not math.isfinite(s) or not 0 <= s <= 1 for s in scores):
            raise ValueError("invalid reranker scores")
        ranked = [dict(row, rerank_score=float(score), answer_eligible=False) for row, score in zip(candidates, scores)]
        return sorted(ranked, key=lambda row: (-row["rerank_score"], -row["fusion_score"], row["id"])), "applied"
    except Exception as error:
        return [dict(row, answer_eligible=False) for row in candidates], f"fallback:{type(error).__name__}"


class PilotRetriever:
    def __init__(self, root: Path = DEFAULT_ROOT, limit: int = 5000):
        from .resource_budget import require_available
        require_available(1536)
        import torch
        torch.set_num_threads(2)
        import chromadb
        from chromadb.config import Settings
        from .bge_embedding import BGEEmbedding
        self.root, self.limit = root.resolve(), limit
        sample = sample_path(self.root, limit)
        target = index_directory(self.root, limit)
        # Check before opening Chroma; never silently create an absent index.
        if not (target / "chroma" / "chroma.sqlite3").is_file():
            raise ValueError("dense index is missing; run dense indexing first")
        self.embedding = BGEEmbedding(batch_size=4)
        self.client = chromadb.PersistentClient(path=str(target / "chroma"), settings=Settings(anonymized_telemetry=False))
        self.collection = self.client.get_collection("huatuo_lite_pilot_bge_zh_v1", embedding_function=None)
        sha = digest(sample)
        self.count = sum(1 for _ in rows(sample))
        metadata = self.collection.metadata or {}
        if (self.collection.count() != self.count or metadata.get("sample_sha256") != sha
                or metadata.get("weight_sha256") != self.embedding.weight_sha256
                or metadata.get("answer_eligible") is not False):
            raise ValueError("incomplete or incompatible dense index")
        with closing(sqlite3.connect((target / "candidate_fts.sqlite").as_uri() + "?mode=ro", uri=True)) as db:
            fts_metadata = dict(db.execute("SELECT key,value FROM metadata"))
            if fts_metadata.get("sample_sha256") != sha or db.execute("SELECT count(*) FROM records").fetchone()[0] != self.count:
                raise ValueError("lexical and dense indexes refer to different samples")
        self.sample_sha256 = sha

    def retrieve(self, query: str, candidates: int = 24) -> dict:
        if not query.strip() or len(query) > 2000 or not 1 <= candidates <= 100:
            raise ValueError("query must be 1..2000 characters; candidates must be 1..100")
        started = time.perf_counter()
        result = self.collection.query(query_embeddings=self.embedding.embed_queries([query]),
                                       n_results=min(candidates, self.count), include=["documents", "distances"])
        dense = []
        for record_id, text, distance in zip(result["ids"][0], result["documents"][0], result["distances"][0]):
            question, _, answer = text.partition("\n")
            dense.append({"id": record_id, "question": question, "answer": answer,
                          "distance": distance, "answer_eligible": False})
        dense_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        lexical = lexical_search(self.root, self.limit, query, candidates)
        hybrid = fuse(dense, lexical)
        return {"dense": dense, "hybrid": hybrid, "answer_eligible": False,
                "dense_ms": round(dense_ms, 1), "lexical_ms": round((time.perf_counter()-started)*1000, 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--mode", choices=["dense", "hybrid", "rerank"], default="dense")
    args = parser.parse_args()
    result = PilotRetriever(args.root, args.limit).retrieve(args.query)
    status = "disabled"
    selected = result["dense" if args.mode == "dense" else "hybrid"]
    if args.mode == "rerank":
        from .resource_budget import MemoryBudgetError, require_available
        try:
            require_available(2304)
            from .bge_reranker import BGEReranker
            selected, status = rerank(args.query, selected[:12], BGEReranker(batch_size=1, max_length=512))
        except MemoryBudgetError:
            status = "fallback:insufficient_memory"
    print(json.dumps({"research_only": True, "answer_eligible": False, "reranker_status": status,
                      "hits": selected[:5]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
