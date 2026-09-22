"""Runtime access and minimal privacy-preserving retrieval metrics."""

import os
import json
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from .knowledge_base import MedicalKnowledgeBase
from .bge_embedding import BGEEmbedding
from .local_embedding import ChineseHashEmbedding

_lock = threading.Lock()
_kb_init_lock = threading.Lock()
_stats = {"queries": 0, "queries_with_hits": 0, "errors": 0, "total_latency_ms": 0.0}
_log_path = Path(__file__).resolve().parents[1] / "logs" / "medical_retrieval.jsonl"


def _write_event(event: dict) -> None:
    """Record only operational data; never persist the health question."""
    event["at_utc"] = datetime.now(timezone.utc).isoformat()
    try:
        _log_path.parent.mkdir(parents=True, exist_ok=True)
        with _log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


@lru_cache(maxsize=4)
def get_knowledge_base(preview: bool = False, research_mode: bool | None = None) -> MedicalKnowledgeBase:
    import chromadb
    from chromadb.config import Settings
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if preview and os.getenv("NODE_ENV") != "development":
        raise ValueError("medical preview is available only in development")
    if research_mode is None:
        research_mode = os.getenv("MEDICAL_RESEARCH_MODE", "false").lower() == "true"
    if research_mode and (preview or os.getenv("NODE_ENV") != "development"):
        raise ValueError("medical research index is available only in development")
    # Chroma reuses one local client per path within a process. Match the
    # existing vector client settings to avoid a shared-client ValueError.
    settings = Settings(anonymized_telemetry=False, allow_reset=True)
    if os.getenv("CHROMA_CLIENT_MODE", "local").lower() == "http":
        client = chromadb.HttpClient(
            host=os.getenv("CHROMA_HOST", "localhost"),
            port=int(os.getenv("CHROMA_PORT", "8000")), settings=settings,
        )
    else:
        # Keep the same path string as Aide's existing Chroma client. Chroma
        # caches local clients by path within a process.
        client = chromadb.PersistentClient(
            path=os.getenv("CHROMA_PERSIST_DIR", "./chroma_db"), settings=settings
        )
    if preview:
        embedding = ChineseHashEmbedding()
        model_name = embedding.name()
    else:
        embedding = BGEEmbedding(batch_size=int(os.getenv("MEDICAL_BGE_BATCH_SIZE", "8")))
        model_name = embedding.name()
    return MedicalKnowledgeBase(
        client, embedding, model_name, preview=preview, research_mode=research_mode
    )


def search_with_metrics(query: str, preview: bool = False, limit: int = 5):
    start = time.perf_counter()
    try:
        # lru_cache does not serialize a cache miss.  The first two MCP tool
        # calls can arrive concurrently after startup, which may make Chroma
        # initialize the same local tenant twice.  Serialize only this one
        # time-sensitive initialization path; normal searches remain parallel.
        with _kb_init_lock:
            kb = get_knowledge_base(preview)
        # An empty published index must not call a remote embedding service or
        # silently fall through to the development draft collection.
        try:
            hits = kb.search(query, limit=limit) if kb.collection.count() else []
        except TypeError:
            # A separate sync process can replace Chroma rows while this MCP
            # process still holds collection/lexical caches. Recreate the
            # runtime once so data refreshes do not require a manual restart.
            with _kb_init_lock:
                get_knowledge_base.cache_clear()
                kb = get_knowledge_base(preview)
            hits = kb.search(query, limit=limit) if kb.collection.count() else []
    except Exception as error:
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        with _lock:
            _stats["errors"] += 1
            _write_event({"preview": preview, "error": type(error).__name__, "latency_ms": latency_ms})
        raise
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    with _lock:
        _stats["queries"] += 1
        _stats["queries_with_hits"] += bool(hits)
        _stats["total_latency_ms"] += latency_ms
        _write_event({"preview": preview, "hit_doc_ids": list(dict.fromkeys(h.doc_id for h in hits)), "latency_ms": latency_ms})
    return hits


def retrieval_stats() -> dict:
    with _lock:
        stats = _stats.copy()
    queries = stats["queries"]
    return {
        "queries": queries,
        "queries_with_hits": stats["queries_with_hits"],
        "errors": stats["errors"],
        "average_latency_ms": round(stats["total_latency_ms"] / queries, 1) if queries else None,
    }
