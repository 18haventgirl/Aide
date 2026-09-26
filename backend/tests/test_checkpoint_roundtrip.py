"""对话状态检查点：SQLite 是唯一真相

阶段 1 的 ask() 每次都从零开始，模型看不到上一轮。接上 checkpointer 后要成立的是：
同一 thread_id 续得上、换个连接也续得上、不同 thread_id 互不串台。
注意 build_checkpointer() 是异步上下文管理器，运行时必须长期持有它，
建完图就退出 with 块等于把连接关掉，下一轮直接报错。
"""

import asyncio

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field as PField

from agent.checkpoint import build_checkpointer, checkpoint_path
from agent.context import UserContext
from agent.graph import build_agent


class EchoModel(BaseChatModel):
    """护栏问话一律放行，业务作答按 replies 依次给出，并记录每轮看到几条用户消息"""

    replies: list = PField(default_factory=list)
    seen_history: list = PField(default_factory=list)
    calls: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "echo"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        prompt = " ".join(str(getattr(m, "content", "")) for m in messages)
        if "安全审查器" in prompt:
            content = "SAFE\n正常"
        elif "相关性审查器" in prompt:
            content = "RELEVANT\n在范围内"
        else:
            self.seen_history.append(len([m for m in messages if isinstance(m, HumanMessage)]))
            content = self.replies[min(self.calls, len(self.replies) - 1)]
            self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


def _use_db(tmp_path, monkeypatch, name="cp.sqlite"):
    path = tmp_path / name
    monkeypatch.setenv("CHECKPOINT_DB", str(path))
    return path


async def _chat(agent, thread_id, text, user_id=3):
    return await agent.ainvoke(
        {"messages": [HumanMessage(content=text)]},
        config={"configurable": {"thread_id": thread_id}},
        context=UserContext(user_id=user_id),
    )


async def _messages_of(agent, thread_id):
    snapshot = await agent.aget_state({"configurable": {"thread_id": thread_id}})
    return (snapshot.values or {}).get("messages", [])


def test_checkpoint_path_honours_env_override(tmp_path, monkeypatch):
    _use_db(tmp_path, monkeypatch)
    assert checkpoint_path().endswith("cp.sqlite")


def test_checkpoint_path_defaults_inside_backend(tmp_path, monkeypatch):
    monkeypatch.delenv("CHECKPOINT_DB", raising=False)
    relative = checkpoint_path().replace("\\", "/")
    assert relative == "data/lg-aide-checkpoints.sqlite"


def test_build_checkpointer_creates_missing_parent_dir(tmp_path, monkeypatch):
    nested = tmp_path / "deep" / "nested" / "cp.sqlite"
    monkeypatch.setenv("CHECKPOINT_DB", str(nested))

    async def open_it():
        async with build_checkpointer() as saver:
            return await saver.aget_tuple({"configurable": {"thread_id": "nope"}})

    assert asyncio.run(open_it()) is None
    assert nested.exists()


def test_same_thread_keeps_history(tmp_path, monkeypatch):
    _use_db(tmp_path, monkeypatch)

    async def run():
        model = EchoModel(replies=["第一轮回答", "第二轮回答"])
        async with build_checkpointer() as saver:
            agent = await build_agent(model, tools=[], checkpointer=saver)
            await _chat(agent, "t-a", "你好")
            await _chat(agent, "t-a", "我叫小王")
            messages = await _messages_of(agent, "t-a")
            return [str(m.content) for m in messages], model.seen_history

    contents, seen = asyncio.run(run())

    assert "我叫小王" in contents and "你好" in contents
    assert contents.count("第一轮回答") == 1 and contents.count("第二轮回答") == 1
    assert seen == [1, 2]                 # 第二轮模型看见了上一轮的提问


def test_history_survives_a_reopened_connection(tmp_path, monkeypatch):
    """换一个 checkpointer 实例（等价于后端重启）还能接上同一线程"""
    _use_db(tmp_path, monkeypatch)

    async def first():
        async with build_checkpointer() as saver:
            agent = await build_agent(EchoModel(replies=["上一轮的答案"]), tools=[],
                                      checkpointer=saver)
            await _chat(agent, "t-b", "先聊这句")

    async def second():
        model = EchoModel(replies=["接得上了"])
        async with build_checkpointer() as saver:
            agent = await build_agent(model, tools=[], checkpointer=saver)
            state = await _chat(agent, "t-b", "接着刚才的说")
            return [str(m.content) for m in state["messages"]], model.seen_history

    asyncio.run(first())
    contents, seen = asyncio.run(second())

    assert "先聊这句" in contents
    assert "上一轮的答案" in contents
    assert seen == [2]                    # 1 条历史提问 + 本轮提问


def test_threads_do_not_leak_into_each_other(tmp_path, monkeypatch):
    _use_db(tmp_path, monkeypatch)

    async def run():
        async with build_checkpointer() as saver:
            agent = await build_agent(EchoModel(replies=["甲线程答", "乙线程答"]), tools=[],
                                      checkpointer=saver)
            await _chat(agent, "thread-a", "甲的秘密")
            await _chat(agent, "thread-b", "乙的秘密")
            return (
                [str(m.content) for m in await _messages_of(agent, "thread-a")],
                [str(m.content) for m in await _messages_of(agent, "thread-b")],
            )

    a, b = asyncio.run(run())

    assert "甲的秘密" in a and "乙的秘密" not in a
    assert "乙的秘密" in b and "甲的秘密" not in b


def test_runtime_wires_the_checkpointer_and_keeps_the_connection(tmp_path, monkeypatch):
    """AideRuntime.ensure_ready 必须长期持有 saver；否则第二轮 ask() 会撞在已关闭的连接上"""
    _use_db(tmp_path, monkeypatch)

    import agent.model as agent_model
    import agent.tools.mcp as mcp_module

    async def no_mcp(*args, **kwargs):
        return []            # MCP 未连接时 runtime 照样能以纯对话模式建图

    model = EchoModel(replies=["第一轮", "第二轮"])
    monkeypatch.setattr(agent_model, "build_chat_model", lambda *a, **k: model)
    monkeypatch.setattr(mcp_module, "load_mcp_tools", no_mcp)

    from agent.runtime import AideRuntime

    async def run():
        runtime = AideRuntime()
        first = await runtime.ask(3, "conv-x", "你好")
        second = await runtime.ask(3, "conv-x", "记住我叫小王")
        await runtime.aclose()
        return first, second

    first, second = asyncio.run(run())

    assert first.error is None and second.error is None
    assert second.text == "第二轮"
    assert model.seen_history == [1, 2]   # 第二轮真接上了第一轮，且连接没被提前关掉


def test_runtime_recovers_after_close(tmp_path, monkeypatch):
    """aclose() 之后再 ask 必须能自愈重建，而不是拿着死连接一直报错"""
    _use_db(tmp_path, monkeypatch)

    import agent.model as agent_model
    import agent.tools.mcp as mcp_module

    async def no_mcp(*args, **kwargs):
        return []            # MCP 未连接时 runtime 照样能以纯对话模式建图

    model = EchoModel(replies=["答一", "答二"])
    monkeypatch.setattr(agent_model, "build_chat_model", lambda *a, **k: model)
    monkeypatch.setattr(mcp_module, "load_mcp_tools", no_mcp)

    from agent.runtime import AideRuntime

    async def run():
        runtime = AideRuntime()
        first = await runtime.ask(3, "conv-y", "你好")
        await runtime.aclose()
        second = await runtime.ask(3, "conv-y", "再说一句")
        await runtime.aclose()
        return first, second

    first, second = asyncio.run(run())

    assert first.error is None
    assert second.error is None, second.error
    assert model.seen_history == [1, 2]   # 重开连接后同一线程的历史仍在
