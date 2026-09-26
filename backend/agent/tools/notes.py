"""笔记工具：暴露给模型的检索与新建

工具不接受 user_id 参数，身份一律取自 runtime.context：把 user_id 交给模型填，
等于允许它检索或写入别人的笔记。
"""

import logging
from typing import Any, List, Optional

from langchain.tools import ToolRuntime, tool

from agent.context import UserContext

logger = logging.getLogger(__name__)

SNIPPET_CHARS = 200


def _note_service():
    """取笔记服务单例（写入与检索都在它内部走向量库）"""
    try:
        from service.service_manager import service_manager
        from service.services.note_service import NoteService
        return service_manager.get_service("note_service", NoteService)
    except Exception as e:
        logger.warning(f"笔记服务不可用: {e}")
        return None


def _user_id(runtime: Optional[ToolRuntime]) -> Optional[int]:
    context = getattr(runtime, "context", None)
    return getattr(context, "user_id", None)


def _field(hit: Any, key: str) -> Any:
    """向量检索返回 dict，关键词检索返回 ORM 对象，两种形状都要能格式化"""
    if isinstance(hit, dict):
        return hit.get(key)
    return getattr(hit, key, None)


def _format_hits(hits: List[Any]) -> str:
    lines = []
    for hit in hits:
        tag = _field(hit, "tag")
        title = _field(hit, "title") or "无标题"
        body = (_field(hit, "text") or _field(hit, "content") or "").strip()
        snippet = body[:SNIPPET_CHARS]
        lines.append(f"- {title}（{tag}）: {snippet}" if tag else f"- {title}: {snippet}")
    return "\n".join(lines)


@tool
def search_my_notes(query: str, top_k: int = 5,
                    runtime: ToolRuntime[UserContext] = None) -> str:
    """检索我的笔记，按相关度返回标题、标签与正文片段"""
    service = _note_service()
    if service is None:
        return "笔记服务当前不可用"
    user_id = _user_id(runtime)
    if user_id is None:
        return "缺少用户上下文，无法检索笔记"

    limit = max(1, min(top_k, 20))
    try:
        hits = service.search_notes_by_vector(user_id, query, limit=limit)
    except Exception as e:
        logger.warning(f"笔记向量检索失败，回退关键词检索: {e}")
        hits = []
    if not hits:
        try:
            hits = service.search_notes(user_id, query, limit=limit)
        except Exception as e:
            logger.warning(f"笔记关键词检索也失败了: {e}")
            hits = []
    if not hits:
        return "没有找到相关笔记"
    return _format_hits(hits)


@tool
def save_note(title: str, content: str = "", tag: str = "",
              runtime: ToolRuntime[UserContext] = None) -> str:
    """给我自己新建一条笔记（标题必填；标签是自由文本，最多 50 字；正文会进入语义索引）"""
    service = _note_service()
    if service is None:
        return "笔记服务当前不可用"
    user_id = _user_id(runtime)
    if user_id is None:
        return "缺少用户上下文，无法保存笔记"

    note = service.create_note(user_id=user_id, title=title, content=content,
                               tag=tag or None, status="active")
    if note is None:
        return "笔记保存失败（标题/标签不合法，或用户不存在）"
    return f"已保存笔记《{title}》，id={_field(note, 'id')}"
