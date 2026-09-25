"""RAG 笔记工具与 MCP 工具装载

工具由模型调用，任何异常都必须变成给模型看的字符串；user_id 只能来自
runtime.context，模型无权指定，否则用户可以检索别人的笔记。
"""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from langchain.tools import ToolRuntime

from agent.context import UserContext
from agent.tools import notes as notes_mod
from agent.tools.notes import save_note, search_my_notes


def _runtime(user_id: int = 7):
    return ToolRuntime(
        state=None,
        context=UserContext(user_id=user_id),
        config=None,
        stream_writer=None,
        tool_call_id="call-1",
        store=None,
        tools=[],
    )


class FakeNoteService:
    """记录调用参数，按脚本返回笔记服务的三种结果"""

    def __init__(self, vector_hits=(), vector_error=None, keyword_hits=(), created="skip"):
        self.vector_hits = list(vector_hits)
        self.vector_error = vector_error
        self.keyword_hits = list(keyword_hits)
        self.created = created
        self.calls = []

    def search_notes_by_vector(self, user_id, query, limit=10):
        self.calls.append(("vector", user_id, query, limit))
        if self.vector_error:
            raise self.vector_error
        return self.vector_hits

    def search_notes(self, user_id, query, limit=20):
        self.calls.append(("keyword", user_id, query, limit))
        return self.keyword_hits

    def create_note(self, user_id, title, content="", tag=None, status="draft"):
        self.calls.append(("create", user_id, title, content, tag, status))
        return None if self.created == "skip" else self.created


@contextmanager
def _service(service):
    with patch.object(notes_mod, "_note_service", lambda: service):
        yield


def _search(service, query="红烧肉怎么做", top_k=5):
    with _service(service):
        return asyncio.run(
            search_my_notes.ainvoke({"query": query, "top_k": top_k, "runtime": _runtime()})
        )


def _search_raw(service, args):
    with _service(service):
        return asyncio.run(search_my_notes.ainvoke(args))


def test_tools_expose_names_and_hide_runtime_from_model():
    assert search_my_notes.name == "search_my_notes"
    assert save_note.name == "save_note"
    assert "笔记" in search_my_notes.description
    assert "笔记" in save_note.description
    # runtime 是注入参数，绝不能出现在给模型的参数表里
    assert set(search_my_notes.tool_call_schema.model_fields) == {"query", "top_k"}
    assert "runtime" not in save_note.tool_call_schema.model_fields


def test_search_formats_vector_hits_with_title_tag_and_snippet():
    service = FakeNoteService(vector_hits=[
        {"note_id": "11", "title": "家常红烧肉", "tag": "菜谱", "score": 0.81,
         "text": "五花肉焯水后冰糖炒色，小火四十分钟。"},
        {"note_id": "12", "title": "无标签笔记", "tag": None, "score": 0.6,
         "text": "x" * 300},
    ])
    out = _search(service)

    assert "- 家常红烧肉（菜谱）: 五花肉焯水后冰糖炒色" in out
    assert "- 无标签笔记: " in out
    assert out.index("家常红烧肉") < out.index("无标签笔记")   # 保持相关度顺序
    assert "x" * 201 not in out                                # 片段截断，别灌满上下文
    assert service.calls == [("vector", 7, "红烧肉怎么做", 5)]  # user_id 取自 context


def test_search_falls_back_to_keyword_when_vector_raises():
    service = FakeNoteService(
        vector_error=RuntimeError("chroma down"),
        keyword_hits=[SimpleNamespace(title="红烧肉备忘", content="少放糖", tag="菜谱")],
    )
    out = _search(service)

    assert "红烧肉备忘" in out
    assert "少放糖" in out
    assert [c[0] for c in service.calls] == ["vector", "keyword"]


def test_search_reports_empty_instead_of_crashing():
    assert _search(FakeNoteService()) == "没有找到相关笔记"


def test_search_clamps_top_k_into_a_safe_range():
    limiter = FakeNoteService()
    _search(limiter, top_k=999)
    assert limiter.calls[-1][3] == 20

    floor = FakeNoteService()
    _search(floor, top_k=0)
    assert floor.calls[-1][3] == 1


def test_search_degrades_to_strings_without_service_or_context():
    with _service(None):
        assert asyncio.run(search_my_notes.ainvoke({"query": "q", "runtime": _runtime()})) \
            == "笔记服务当前不可用"

    out = _search_raw(FakeNoteService(), {"query": "q"})      # 未注入 runtime
    assert isinstance(out, str) and "用户" in out              # 缺上下文也不能抛


def test_save_note_uses_context_identity():
    service = FakeNoteService(created=SimpleNamespace(id=42))
    with _service(service):
        out = asyncio.run(save_note.ainvoke(
            {"title": "会议纪要", "content": "定下周三上线", "tag": "工作",
             "runtime": _runtime(user_id=9)}
        ))

    assert "42" in out
    assert service.calls == [("create", 9, "会议纪要", "定下周三上线", "工作", "active")]


def test_save_note_returns_failure_string_when_service_returns_none():
    with _service(FakeNoteService(created=None)):
        out = asyncio.run(save_note.ainvoke({"title": "t", "runtime": _runtime()}))
    assert "失败" in out


def test_save_note_without_service_or_context_returns_string():
    # 注意：runtime 是注入参数，显式传 None 会被 pydantic 拒；省略键才走"未注入"路径
    with _service(None):
        assert asyncio.run(save_note.ainvoke({"title": "t"})) == "笔记服务当前不可用"
    with _service(FakeNoteService()):
        out = asyncio.run(save_note.ainvoke({"title": "t"}))   # 未注入 runtime
    assert isinstance(out, str) and "用户" in out
