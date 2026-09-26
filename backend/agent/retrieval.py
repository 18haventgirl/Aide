"""笔记检索的两个图钩子

retrieve（before_agent）：每轮跑一次，命中写进 state.retrieved。
inject（wrap_model_call）：每次模型调用时把命中内容作为临时 SystemMessage 插在最新一条
用户消息之前。之所以不写进 messages，是因为 checkpoint 会永久保留状态里的消息，
多轮下来历史会堆满检索片段，既占 token 又让轨迹难读。
"""

import logging
from typing import Any, Dict, List, Optional

from langchain.agents.middleware import before_agent, wrap_model_call
from langchain_core.messages import HumanMessage, SystemMessage

from agent.state import AideState

logger = logging.getLogger(__name__)

RETRIEVAL_NAME = "note_retrieval"
INJECT_NAME = "retrieval_context"
SNIPPET_CHARS = 300
MAX_HITS = 20


def _last_human_text(messages: List[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content or "").strip()
    return ""


def build_retrieval_middleware(k: int = 5, threshold: Optional[float] = None):
    """构造检索钩子；threshold 为 None 时读 SIMILARITY_THRESHOLD 配置"""

    @before_agent(state_schema=AideState, name=RETRIEVAL_NAME)
    async def retrieve(state, runtime):
        user_id = getattr(getattr(runtime, "context", None), "user_id", None)
        query = _last_human_text(state.get("messages", []) or [])
        if user_id is None or not query:
            return {"retrieved": []}

        from core.retrieval.store import note_store

        limit = max(1, min(k, MAX_HITS))
        cut = threshold
        try:
            if cut is None:
                from core.retrieval.config import VectorConfig

                cut = VectorConfig.from_env().similarity_threshold
            pairs = note_store(user_id).similarity_search_with_relevance_scores(query, k=limit)
        except Exception as exc:
            logger.warning(f"笔记检索不可用，本轮不注入: {exc}")
            return {"retrieved": []}

        hits = [{"id": (doc.metadata or {}).get("note_id"),
                 "title": (doc.metadata or {}).get("title") or "无标题",
                 "score": float(score),
                 "text": doc.page_content[:SNIPPET_CHARS]}
                for doc, score in pairs if float(score) >= cut]
        return {"retrieved": hits}

    return retrieve


def build_retrieval_injector():
    """把命中内容临时拼进模型输入

    必须是异步函数：运行时全程走 ainvoke/astream，而同步版 wrap_model_call 在异步
    调用下会直接 NotImplementedError（库明确要求二选一）。
    """

    @wrap_model_call(state_schema=AideState, name=INJECT_NAME)
    async def inject(request, handler):
        hits: List[Dict[str, Any]] = request.state.get("retrieved") or []
        if not hits:
            return await handler(request)

        block = "\n".join(f"- {hit['title']}（相关度 {hit['score']:.2f}）: {hit['text']}"
                          for hit in hits)
        message = SystemMessage(content=f"[笔记检索结果]\n{block}")
        messages = list(request.messages)
        for index in range(len(messages) - 1, -1, -1):
            if isinstance(messages[index], HumanMessage):
                messages.insert(index, message)
                break
        else:
            messages.append(message)
        return await handler(request.override(messages=messages))

    return inject
