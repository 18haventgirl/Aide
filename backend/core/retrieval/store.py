"""笔记向量库：每用户一个 Chroma 集合

隔离靠集合命名空间，而不是 where={"user_id":...} 过滤：过滤条件一旦在某处漏传，
就是跨用户读取；分集合把这件事变成不可能。
集合必须显式声明 hnsw:space=cosine —— Chroma 默认是 l2，旧实现把 l2 距离当余弦用过，
检索长期失效（见 docs/PROGRESS.md）。
"""

import logging
import re
from typing import Union

import chromadb
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)

_stores: dict = {}
_http_warned = False


def _embeddings() -> Embeddings:
    from core.retrieval.embeddings import get_embeddings

    return get_embeddings()


def _config():
    from core.retrieval.config import VectorConfig

    return VectorConfig.from_env()


def _persist_dir() -> str:
    return _config().chroma_persist_directory


def _prefix() -> str:
    return _config().chroma_collection_prefix


def _mode() -> str:
    return _config().chroma_client_mode


def collection_name(prefix: str, user_id: Union[int, str]) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", str(user_id))
    return f"{prefix}_user_{sanitized}"


def _warn_if_http() -> None:
    """检索层只走本地持久化模式；显式配了 http 要说清楚，别让人以为数据在 8101"""
    global _http_warned
    if _http_warned:
        return
    if _mode() == "http":
        logger.warning("CHROMA_CLIENT_MODE=http 已不再生效：笔记检索统一使用本地持久化目录")
    _http_warned = True


def note_store(user_id: Union[int, str]) -> Chroma:
    """取该用户的向量库句柄；同一进程内复用"""
    key = str(user_id)
    if key not in _stores:
        _warn_if_http()
        _stores[key] = Chroma(
            collection_name=collection_name(_prefix(), user_id),
            embedding_function=_embeddings(),
            persist_directory=_persist_dir(),
            collection_metadata={"hnsw:space": "cosine"},
        )
        logger.debug(f"笔记向量库就绪: {_stores[key]._collection.name}")
    return _stores[key]


def vector_health() -> dict:
    """给 /api/health 用：能连上并列出集合就算健康"""
    try:
        client = chromadb.PersistentClient(path=_persist_dir())
        return {"status": "healthy", "collections": len(client.list_collections())}
    except Exception as exc:
        logger.warning(f"向量库健康检查失败: {exc}")
        return {"status": "unhealthy", "error": str(exc)}
