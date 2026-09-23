"""Runtime access and minimal privacy-preserving retrieval metrics."""

import os
import json
import hashlib
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from .knowledge_base import MedicalKnowledgeBase
from .bge_embedding import BGEEmbedding
from .bge_reranker import BGEReranker
from .local_embedding import ChineseHashEmbedding

_lock = threading.Lock()
_kb_init_lock = threading.Lock()
_stats = {"queries": 0, "queries_with_hits": 0, "errors": 0, "total_latency_ms": 0.0}
_log_path = Path(__file__).resolve().parents[1] / "logs" / "medical_retrieval.jsonl"
_cache_lock = threading.Lock()
_result_cache: OrderedDict[str, tuple[float, list]] = OrderedDict()
_request_context = threading.local()
_warmup_lock = threading.Lock()
_warmed_up = False


@lru_cache(maxsize=1)
def get_reranker():
    if os.getenv("MEDICAL_USE_RERANKER", "true").lower() != "true":
        return None
    try:
        return BGEReranker(
            batch_size=int(os.getenv("MEDICAL_RERANKER_BATCH_SIZE", "8")),
            max_length=int(os.getenv("MEDICAL_RERANKER_MAX_LENGTH", "256")),
        )
    except (FileNotFoundError, ValueError):
        # Installation is optional. The KB reports a deterministic hybrid
        # fallback until the pinned local model has been downloaded.
        return None


def _write_event(event: dict) -> None:
    """Record only operational data; never persist the health question."""
    event["at_utc"] = datetime.now(timezone.utc).isoformat()
    try:
        _log_path.parent.mkdir(parents=True, exist_ok=True)
        with _log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def clear_retrieval_cache() -> None:
    with _cache_lock:
        _result_cache.clear()


def last_search_metrics() -> dict:
    """Return diagnostics for the search completed on the current tool thread."""
    return dict(getattr(_request_context, "diagnostics", {}))


def _cache_key(query: str, preview: bool, limit: int, collection_count: int) -> str:
    normalized = " ".join(query.strip().lower().split())
    value = f"{preview}:{limit}:{collection_count}:{normalized}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _cache_get(key: str):
    now = time.monotonic()
    with _cache_lock:
        item = _result_cache.get(key)
        if item is None:
            return None
        expires_at, hits = item
        if expires_at <= now:
            _result_cache.pop(key, None)
            return None
        _result_cache.move_to_end(key)
        return [hit.model_copy(deep=True) for hit in hits]


def _cache_put(key: str, hits: list) -> None:
    ttl = max(0.0, float(os.getenv("MEDICAL_RETRIEVAL_CACHE_TTL_SECONDS", "60")))
    if ttl == 0:
        return
    capacity = max(1, int(os.getenv("MEDICAL_RETRIEVAL_CACHE_SIZE", "128")))
    with _cache_lock:
        _result_cache[key] = (time.monotonic() + ttl, [hit.model_copy(deep=True) for hit in hits])
        _result_cache.move_to_end(key)
        while len(_result_cache) > capacity:
            _result_cache.popitem(last=False)


def warmup_medical_models() -> dict:
    """Load local models and run one unlogged search before serving users."""
    global _warmed_up
    if _warmed_up:
        return {"status": "already_warm"}
    with _warmup_lock:
        if _warmed_up:
            return {"status": "already_warm"}
        started = time.perf_counter()
        kb = get_knowledge_base(False)
        if kb.collection.count():
            kb.search("成年人常见健康问题", limit=1)
        else:
            kb._embed_queries(["成年人常见健康问题"])
            if kb.reranker is not None:
                kb.reranker.score("健康问题", ["一般健康知识"])
        _warmed_up = True
        return {
            "status": "warmed", "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "reranker": kb.reranker.name() if kb.reranker is not None else None,
        }


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
        client, embedding, model_name, preview=preview, research_mode=research_mode,
        reranker=None if preview else get_reranker(),
        reranker_requested=(not preview and os.getenv("MEDICAL_USE_RERANKER", "true").lower() == "true"),
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
        collection_count = kb.collection.count()
        key = _cache_key(query, preview, limit, collection_count)
        cached = _cache_get(key)
        if cached is not None:
            latency_ms = round((time.perf_counter() - start) * 1000, 1)
            _request_context.diagnostics = {
                "cache_hit": True,
                "selected_count": len(cached),
            }
            with _lock:
                _stats["queries"] += 1
                _stats["queries_with_hits"] += bool(cached)
                _stats["total_latency_ms"] += latency_ms
                _stats["cache_hits"] = _stats.get("cache_hits", 0) + 1
                _write_event({
                    "preview": preview, "cache_hit": True,
                    "hit_doc_ids": list(dict.fromkeys(h.doc_id for h in cached)),
                    "latency_ms": latency_ms,
                })
            return cached
        # An empty published index must not call a remote embedding service or
        # silently fall through to the development draft collection.
        try:
            hits = kb.search(query, limit=limit) if collection_count else []
        except TypeError:
            # A separate sync process can replace Chroma rows while this MCP
            # process still holds collection/lexical caches. Recreate the
            # runtime once so data refreshes do not require a manual restart.
            with _kb_init_lock:
                get_knowledge_base.cache_clear()
                kb = get_knowledge_base(preview)
            hits = kb.search(query, limit=limit) if kb.collection.count() else []
            key = _cache_key(query, preview, limit, kb.collection.count())
    except Exception as error:
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        with _lock:
            _stats["errors"] += 1
            _write_event({"preview": preview, "error": type(error).__name__, "latency_ms": latency_ms})
        raise
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    _cache_put(key, hits)
    diagnostics = kb.search_metrics() if hasattr(kb, "search_metrics") else {}
    diagnostics = {"cache_hit": False, **diagnostics}
    _request_context.diagnostics = diagnostics
    with _lock:
        _stats["queries"] += 1
        _stats["queries_with_hits"] += bool(hits)
        _stats["total_latency_ms"] += latency_ms
        _write_event({
            "preview": preview,
            "hit_doc_ids": list(dict.fromkeys(h.doc_id for h in hits)),
            "latency_ms": latency_ms,
            **diagnostics,
        })
    return hits


def retrieval_stats() -> dict:
    with _lock:
        stats = _stats.copy()
    queries = stats["queries"]
    return {
        "queries": queries,
        "queries_with_hits": stats["queries_with_hits"],
        "errors": stats["errors"],
        "cache_hits": stats.get("cache_hits", 0),
        "average_latency_ms": round(stats["total_latency_ms"] / queries, 1) if queries else None,
    }
