"""长期记忆：跨会话记住用户的长期事实

与笔记的界限：笔记是用户自己写或明确要求写的资料（MySQL + Chroma，面板可见可编辑）；
记忆是助手从对话里沉淀的长期事实，只在图内注入，不进笔记面板。
写入只由模型显式调用 save_memory 决定，不做每轮自动抽取（写放大与隐私都不可控）。
"""

import asyncio
from contextlib import AsyncExitStack

import pytest
from langchain.agents import create_agent
from langchain.tools import ToolRuntime
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.store.memory import IndexConfig
from langgraph.store.sqlite import AsyncSqliteStore
from pydantic import Field as PField

from agent.context import UserContext
from agent.memory import (build_memory_injector, build_memory_middleware,
                          memory_namespace, memory_path)
from agent.state import AideState


class StubModel(BaseChatModel):
    """记录每次看到的消息列表，用来断言"注入但没落历史"

    必须是 BaseChatModel：create_agent 会对 model 调 bind。
    """

    reply: str = "好的"
    seen: list = PField(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "stub"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.reply))])


@pytest.fixture
def any_store(tmp_path):
    """真 store（临时文件 + 假向量）：验证 aput/asearch 与命名空间隔离"""
    handle_holder = []

    async def make():
        stack = AsyncExitStack()
        store = await stack.enter_async_context(AsyncSqliteStore.from_conn_string(
            str(tmp_path / "mem.sqlite"),
            index=IndexConfig(dims=64, embed=DeterministicFakeEmbedding(size=64),
                              fields=["text"])))
        handle_holder.append((stack, store))
        return store

    yield make

    # 关掉连接，否则临时目录里的 sqlite 句柄会留到 GC
    if handle_holder:
        stack, _store = handle_holder[0]
        asyncio.run(stack.aclose())


def _tool_runtime(user_id, store):
    return ToolRuntime(state=None, context=UserContext(user_id=user_id), config=None,
                       stream_writer=None, tool_call_id="call-1", store=store, tools=[])


def _agent(model, middlewares, store):
    return create_agent(model, [], middleware=middlewares, state_schema=AideState,
                        context_schema=UserContext, store=store, name="Aide")


def test_memory_path_honours_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_DB", str(tmp_path / "mem.sqlite"))
    assert memory_path().endswith("mem.sqlite")


def test_namespace_is_per_user():
    assert memory_namespace(3) == ("user", "3", "memory")
    assert memory_namespace(4) != memory_namespace(3)


def test_save_memory_tool_writes_into_user_namespace(any_store):
    from agent.tools.memory import save_memory

    async def run():
        store = await any_store()
        out = await save_memory.ainvoke({"text": "用户在做安卓开发",
                                         "runtime": _tool_runtime(3, store)})
        items = await store.asearch(memory_namespace(3), limit=5)
        return out, [i.value["text"] for i in items]

    out, texts = asyncio.run(run())
    assert "已记住" in out and "用户在做安卓开发" in texts


def test_memory_search_is_injected_but_not_persisted(any_store):
    async def run():
        store = await any_store()
        await store.aput(memory_namespace(3), "job", {"text": "用户在做安卓开发"})
        model = StubModel(reply="你在做安卓开发")
        agent = _agent(model, [build_memory_middleware(limit=3), build_memory_injector()], store)
        state = await agent.ainvoke({"messages": [HumanMessage(content="我是做什么的？")]},
                                    context=UserContext(user_id=3))
        return model.seen[0], state

    seen, state = asyncio.run(run())

    assert any("长期记忆" in str(m.content) for m in seen)                    # 模型看到了
    assert not any("长期记忆" in str(m.content) for m in state["messages"])    # 不进历史


def test_other_users_memories_are_not_visible(any_store):
    async def run():
        store = await any_store()
        await store.aput(memory_namespace(9), "city", {"text": "用户住在成都"})
        model = StubModel(reply="不知道")
        agent = _agent(model, [build_memory_middleware(limit=3), build_memory_injector()], store)
        await agent.ainvoke({"messages": [HumanMessage(content="我住在哪")]},
                            context=UserContext(user_id=3))
        return model.seen[0]

    seen = asyncio.run(run())
    assert not any("成都" in str(m.content) for m in seen)


def test_recall_degrades_without_store():
    """拿不到存储时不注入，也不能抛：记忆是增强项，不是对话的前置条件"""
    async def run():
        model = StubModel()
        agent = _agent(model, [build_memory_middleware(limit=3), build_memory_injector()], None)
        state = await agent.ainvoke({"messages": [HumanMessage(content="我是做什么的？")]},
                                    context=UserContext(user_id=3))
        return model.seen[0], state

    seen, state = asyncio.run(run())
    assert state["memories"] == []
    assert not any("长期记忆" in str(m.content) for m in seen)
