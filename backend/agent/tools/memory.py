"""长期记忆工具：只暴露"记住一条"，不暴露"查别人的"

身份与 store 都取自 runtime，模型无权指定 user_id；写入只在模型显式调用时发生，
不做每轮自动抽取（那会带来不可控的写放大与隐私面）。
"""

import logging
from typing import Optional
from uuid import uuid4

from langchain.tools import ToolRuntime, tool

from agent.context import UserContext

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 500


def _user_id(runtime: Optional[ToolRuntime]) -> Optional[int]:
    context = getattr(runtime, "context", None)
    return getattr(context, "user_id", None)


@tool
async def save_memory(text: str, runtime: ToolRuntime[UserContext] = None) -> str:
    """记住一条关于用户的长期事实或偏好（跨会话有效；只存长期有效内容，一次性问题不要存）"""
    user_id = _user_id(runtime)
    store = getattr(runtime, "store", None)
    if user_id is None or store is None:
        return "缺少用户身份或记忆存储，未能记住"

    body = (text or "").strip()
    if not body:
        return "要记住的内容是空的，未能记住"

    from agent.memory import memory_namespace

    key = f"mem_{uuid4().hex[:8]}"
    try:
        await store.aput(memory_namespace(user_id), key, {"text": body[:MAX_TEXT_CHARS]})
    except Exception as exc:
        logger.warning(f"长期记忆写入失败: {exc}")
        return "记忆写入失败，未能记住"
    return "已记住"
