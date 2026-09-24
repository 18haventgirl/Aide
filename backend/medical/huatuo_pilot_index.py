"""Isolated Huatuo-Lite retrieval experiment; no connection to the answer corpus.

FTS5 BM25 uses presegmented Chinese text stored on disk. Dense indexing uses
the installed BGE model in small batches and can resume at completed records.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

from .huatuo_lite import DEFAULT_ROOT, POLICY_VERSION, digest, directory, filename, lock, write_report
from .resource_budget import MemoryBudgetError, memory_status, require_available


def sample_path(root: Path, limit: int) -> Path:
    return directory(root) / "normalized" / filename(f"pilot-{limit}-{POLICY_VERSION}", "jsonl")


def index_directory(root: Path, limit: int) -> Path:
    return directory(root) / "indexes" / f"pilot-{limit}-{POLICY_VERSION}"


def rows(path: Path):
    with path.open(encoding="utf-8") as source:
        for line in source:
            yield json.loads(line)


def fts_index(root: Path = DEFAULT_ROOT, limit: int = 5000) -> dict:
    from .lexical import tokens
    sample = sample_path(root, limit)
    target = index_directory(root, limit) / "candidate_fts.sqlite"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".sqlite.part")
    if temporary.exists():
        temporary.unlink()
    started = time.perf_counter()
    count = 0
    with closing(sqlite3.connect(temporary)) as db:
        db.execute("PRAGMA cache_size=-4096")
        db.executescript("""
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE records(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED, terms, tokenize='unicode61');
        """)
        for row in rows(sample):
            db.execute("INSERT INTO records VALUES (?,?)", (row["id"], json.dumps(row, ensure_ascii=False)))
            db.execute("INSERT INTO search VALUES (?,?)", (row["id"], " ".join(tokens(row["question"] + "\n" + row["answer"]))))
            count += 1
            if count % 250 == 0:
                db.commit()
        db.execute("INSERT INTO metadata VALUES ('sample_sha256',?)", (digest(sample),))
        db.execute("INSERT INTO metadata VALUES ('answer_eligible','false')")
        db.commit()
    temporary.replace(target)
    report = {"rows": count, "index": "SQLite FTS5 BM25 with jieba tokens", "index_bytes": target.stat().st_size,
              "elapsed_seconds": round(time.perf_counter() - started, 2), "memory": memory_status(), "answer_eligible": False}
    write_report(target.parent / "fts_report.json", report)
    return report


def lexical_search(root: Path, limit: int, query: str, k: int = 5) -> list[dict]:
    from .lexical import tokens
    terms = list(dict.fromkeys(tokens(query)))[:32]
    if not terms:
        return []
    expression = " OR ".join('"' + word.replace('"', '""') + '"' for word in terms)
    target = index_directory(root, limit) / "candidate_fts.sqlite"
    with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as db:
        return [dict(json.loads(payload), lexical_score=-score) for payload, score in db.execute(
            "SELECT r.payload,bm25(search) AS score FROM search JOIN records r ON r.id=search.id "
            "WHERE search MATCH ? ORDER BY score LIMIT ?", (expression, k))]


def dense_index(root: Path = DEFAULT_ROOT, limit: int = 5000) -> dict:
    before = require_available(1536)
    import torch
    torch.set_num_threads(2)
    import chromadb
    from chromadb.config import Settings
    from .bge_embedding import BGEEmbedding
    sample = sample_path(root, limit)
    target = index_directory(root, limit)
    embedding = BGEEmbedding(batch_size=4)
    metadata = {"sample_sha256": digest(sample), "embedding": embedding.name(), "weight_sha256": embedding.weight_sha256,
                "hnsw:space": "cosine", "answer_eligible": False}
    client = chromadb.PersistentClient(path=str(target / "chroma"), settings=Settings(anonymized_telemetry=False))
    collection = client.get_or_create_collection("huatuo_lite_pilot_bge_zh_v1", metadata=metadata, embedding_function=None)
    if collection.metadata != metadata:
        raise ValueError("pilot sample or model changed; use a new versioned index directory")
    started = time.perf_counter()
    embedding._load()
    batch, encoded, skipped = [], 0, 0

    def flush():
        nonlocal encoded, skipped
        require_available(768)
        existing = set(collection.get(ids=[row["id"] for row in batch], include=[])["ids"])
        pending = [row for row in batch if row["id"] not in existing]
        skipped += len(existing)
        if not pending:
            batch.clear()
            return
        ids = [row["id"] for row in pending]
        texts = [row["question"] + "\n" + row["answer"] for row in pending]
        # Preserve each QA pair as one unit. Never silently truncate a warning.
        lengths = [len(value) for value in embedding._tokenizer(texts, truncation=False)["input_ids"]]
        if any(length > 512 for length in lengths):
            raise ValueError("QA exceeds embedding context; revise screening, do not truncate")
        collection.upsert(ids=ids, documents=texts, embeddings=embedding.embed_documents(texts),
                          metadatas=[{"source_record_id": str(row["source_record_id"]), "source_line": row["source_line"],
                                      "language": "zh", "answer_eligible": False} for row in pending])
        encoded += len(pending)
        batch.clear()

    for row in rows(sample):
        batch.append(row)
        if len(batch) == 16:
            flush()
            print(f"embedded {encoded}; resumed {skipped}", flush=True)
    if batch:
        flush()
    report = {"indexed_rows": collection.count(), "newly_encoded": encoded, "resumed_rows": skipped,
              "elapsed_seconds": round(time.perf_counter() - started, 2), "memory_before": before,
              "memory_after": memory_status(), "embedding": embedding.name(), "answer_eligible": False}
    write_report(target / "dense_report.json", report)
    write_report(target / "dense_status.json", {"status": "complete", **report})
    return report


def dense_smoke(root: Path = DEFAULT_ROOT, limit: int = 5000) -> dict:
    """Verify persisted vectors and query encoding; not a relevance benchmark."""
    require_available(1536)
    import torch
    torch.set_num_threads(2)
    import chromadb
    from chromadb.config import Settings
    from .bge_embedding import BGEEmbedding
    sample = sample_path(root, limit)
    target = index_directory(root, limit)
    client = chromadb.PersistentClient(path=str(target / "chroma"), settings=Settings(anonymized_telemetry=False))
    collection = client.get_collection("huatuo_lite_pilot_bge_zh_v1", embedding_function=None)
    embedding = BGEEmbedding(batch_size=4)
    expected = sum(1 for _ in rows(sample))
    if collection.count() != expected or collection.metadata["sample_sha256"] != digest(sample):
        raise ValueError("incomplete index or sample mismatch")
    if collection.metadata["weight_sha256"] != embedding.weight_sha256:
        raise ValueError("query model differs from index model")
    queries = ["成年人怎么改善睡眠", "跑步后喉咙痛怎么办", "发烧了怎么补水", "便秘如何调整饮食",
               "每天喝多少水", "戒烟有什么办法", "感冒后应该注意什么", "久坐怎样活动身体"]
    hits = []
    for query in queries:
        started = time.perf_counter()
        result = collection.query(query_embeddings=embedding.embed_queries([query]), n_results=3,
                                  include=["documents", "distances"])
        hits.append({"query": query, "elapsed_ms": round((time.perf_counter()-started)*1000, 1),
                     "ids": result["ids"][0], "distances": result["distances"][0],
                     "questions": [text.split("\n", 1)[0] for text in result["documents"][0]]})
    report = {"indexed_rows": expected, "dimensions": embedding.dimensions, "answer_eligible": False,
              "evaluation": "smoke_only_no_relevance_labels", "queries": hits, "memory": memory_status()}
    write_report(target / "dense_smoke.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["fts", "dense", "search", "dense-smoke"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--query", default="成年人如何改善睡眠")
    args = parser.parse_args()
    if args.command == "fts":
        result = fts_index(args.root, args.limit)
    elif args.command == "dense":
        try:
            result = dense_index(args.root, args.limit)
        except MemoryBudgetError as error:
            result = {"status": "blocked_by_available_memory", "reason": str(error),
                      "memory": memory_status(), "resumable": True, "answer_eligible": False}
            write_report(index_directory(args.root, args.limit) / "dense_status.json", result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            raise SystemExit(2)
    elif args.command == "dense-smoke":
        result = dense_smoke(args.root, args.limit)
    else:
        result = {"research_candidates_only": True, "hits": lexical_search(args.root, args.limit, args.query)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
