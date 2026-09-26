"""长期记忆：LangGraph Store + 语义索引

短期记忆（同一会话的多轮）由 checkpointer 承担；这里管的是跨会话、按用户隔离的长期事实。

不引新数据库（还是 SQLite，一个独立文件），也不引新模型（复用笔记检索那套本地 bge）。
必须用异步接口：同步 put 在事件循环里会抛 InvalidStateError（实测）。
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List

from langchain.agents.middleware import before_agent, wrap_model_call
from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import AideState

logger = logging.getLogger(__name__)

DEFAULT_PATH = "data/lg-aide-memory.sqlite"
RECALL_NAME = "user_memory"
INJECT_NAME = "memory_context"
MAX_LIMIT = 10


def memory_path() -> str:
    return os.getenv("MEMORY_DB", DEFAULT_PATH)


def memory_namespace(user_id: Any) -> tuple:
    """命名空间带 user 前缀，跨用户读取在结构上不可能（不是靠"记得传过滤条件"）"""
    return ("user", str(user_id), "memory")


@asynccontextmanager
async def build_memory_store() -> AsyncIterator[Any]:
    """打开（并长持有）长期记忆存储；语义索引复用本地 embedding

    调用方要用 AsyncExitStack 持有这个上下文：建完就退出会让下一轮撞在已关闭的连接上
    （和 checkpointer 同一个道理）。
    """
    from langgraph.store.memory import IndexConfig
    from langgraph.store.sqlite import AsyncSqliteStore

    from core.retrieval.config import VectorConfig
    from core.retrieval.embeddings import get_embeddings

    path = memory_path()
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    index = IndexConfig(dims=VectorConfig.from_env().vector_dimension,
                        embed=get_embeddings(), fields=["text"])
    async with AsyncSqliteStore.from_conn_string(path, index=index) as store:
        logger.info(f"长期记忆存储就绪: {path}")
        yield store


def _last_human_text(messages: List[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content or "").strip()
    return ""


def build_memory_middleware(limit: int = 3):
    """每轮一次语义召回，命中写进 state.memories（和笔记检索同一个模式）"""

    @before_agent(state_schema=AideState, name=RECALL_NAME)
    async def recall(state, runtime):
        user_id = getattr(getattr(runtime, "context", None), "user_id", None)
        store = getattr(runtime, "store", None)
        query = _last_human_text(state.get("messages", []) or [])
        if user_id is None or store is None or not query:
            return {"memories": []}

        try:
            items = await store.asearch(memory_namespace(user_id), query=query,
                                        limit=max(1, min(limit, MAX_LIMIT)))
        except Exception as exc:
            logger.warning(f"长期记忆检索不可用，本轮不注入: {exc}")
            return {"memories": []}

        return {"memories": [{"key": item.key, "text": str(item.value.get("text", ""))}
                             for item in items]}

    return recall


def build_memory_injector():
    """把召回结果临时拼进模型输入，不写回 messages

    写回会被 checkpoint 永久保留：同一句长期事实每轮复读一次，既占 token 又让轨迹难读。
    必须异步：运行时全程 ainvoke/astream，同步版 wrap_model_call 在异步调用下直接
    NotImplementedError。
    """

    @wrap_model_call(state_schema=AideState, name=INJECT_NAME)
    async def inject(request, handler):
        memories: List[Dict[str, Any]] = request.state.get("memories") or []
        if not memories:
            return await handler(request)

        block = "\n".join(f"- {memory['text']}" for memory in memories if memory.get("text"))
        if not block:
            return await handler(request)

        message = SystemMessage(content=f"[长期记忆] 关于该用户的既有事实：\n{block}")
        messages = list(request.messages)
        for index in range(len(messages) - 1, -1, -1):
            if isinstance(messages[index], HumanMessage):
                messages.insert(index, message)
                break
        else:
            messages.append(message)
        return await handler(request.override(messages=messages))

    return inject
