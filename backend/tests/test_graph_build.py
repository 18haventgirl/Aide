"""建图与运行时入口

两条硬要求：
1) MCP 的 user_data_* 工具要求模型自己填 user_id，图这一层必须用上下文里的真实
   身份覆写，否则模型（或被诱导的用户）可以读写别人的数据。
2) 模型不可用 / 图执行异常时，ask() 返回带 error 的结果而不是抛给 WebSocket 层。
"""

import asyncio

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain.tools import tool
from pydantic import Field as PField

from agent.context import UserContext
from agent.graph import build_agent, default_tools
from agent.runtime import AideAnswer, AideRuntime


class ScriptedModel(BaseChatModel):
    """按脚本产出消息的替身。

    护栏判定和业务作答共用同一个模型实例，所以先按 system prompt 认出"这是护栏在问"，
    一律放行；剩下的调用才按 replies 依次作答。不这样区分的话，脚本会被两次判定吃掉。
    """

    replies: list = PField(default_factory=list)
    calls: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        prompt = " ".join(str(getattr(m, "content", "")) for m in messages)
        if "安全审查器" in prompt:
            verdict = "SAFE\n日常请求，不涉及风险"
        elif "相关性审查器" in prompt:
            verdict = "RELEVANT\n在助手服务范围内"
        else:
            verdict_payload = self.replies[min(self.calls, len(self.replies) - 1)]
            self.calls += 1
            return ChatResult(generations=[
                ChatGeneration(message=AIMessage(**verdict_payload))
            ])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=verdict))])


@tool
def fake_user_todos(user_id: int) -> str:
    """替身工具：像 MCP 那样要求模型提供 user_id"""
    return f"saw user_id={user_id}"


def _invoke(model, tools, text="我有什么待办", user_id=7):
    """真跑一遍图，返回 state；身份只从 context 来"""
    async def go():
        agent = await build_agent(model, tools=tools)
        ctx = UserContext(user_id=user_id)
        return await agent.ainvoke({"messages": [HumanMessage(content=text)]}, context=ctx)

    return asyncio.run(go())


def test_build_agent_requires_model():
    with pytest.raises(ValueError) as exc:
        asyncio.run(build_agent(None, tools=[]))
    assert "模型" in str(exc.value)


def test_build_agent_returns_runnable_with_default_tools():
    agent = asyncio.run(build_agent(ScriptedModel(), tools=[fake_user_todos]))
    assert hasattr(agent, "ainvoke")
    assert {t.name for t in default_tools()} == {"search_my_notes", "save_note"}


def test_tools_without_user_id_are_untouched():
    @tool
    def weather(city: str) -> str:
        """查天气"""
        return f"{city} 晴"

    model = ScriptedModel(replies=[
        {"content": "", "tool_calls": [{"name": "weather", "args": {"city": "上海"}, "id": "c1"}]},
        {"content": "上海晴"},
    ])
    state = _invoke(model, [weather])

    tool_msg = next(m for m in state["messages"] if isinstance(m, ToolMessage))
    assert tool_msg.content == "上海 晴"


def test_model_supplied_user_id_is_overwritten_by_context():
    model = ScriptedModel(replies=[
        {"content": "", "tool_calls": [
            {"name": "fake_user_todos", "args": {"user_id": 999}, "id": "c1"}]},
        {"content": "你有一条待办"},
    ])
    state = _invoke(model, [fake_user_todos])

    tool_msg = next(m for m in state["messages"] if isinstance(m, ToolMessage))
    assert tool_msg.content == "saw user_id=7"      # 模型填的 999 被丢掉


def _runtime_with(messages, has_memory=False):
    class StubAgent:
        def __init__(self, messages):
            self.messages = messages
            self.kwargs = None

        async def ainvoke(self, payload, config=None, context=None):
            self.kwargs = {"payload": payload, "config": config, "context": context}
            return {"messages": self.messages}

    runtime = AideRuntime()
    runtime._agent = StubAgent(messages)
    runtime._has_memory = has_memory
    runtime.ensure_ready = lambda: asyncio.sleep(0)
    return runtime


def test_ask_collects_answer_and_tool_events():
    messages = [
        HumanMessage(content="明天上海天气"),
        AIMessage(content="", tool_calls=[{"name": "weather_get_daily_weather_forecast",
                                           "args": {"city": "上海"}, "id": "c1"}]),
        ToolMessage(content="多云转晴", tool_call_id="c1",
                    name="weather_get_daily_weather_forecast"),
        AIMessage(content="上海明天多云转晴"),
    ]
    runtime = _runtime_with(messages)
    answer = asyncio.run(runtime.ask(3, "conv-1", "明天上海天气"))

    assert answer.error is None
    assert answer.text == "上海明天多云转晴"
    assert answer.blocked is False
    kinds = [e["type"] for e in answer.tool_events]
    assert kinds == ["tool_call", "tool_output"]
    assert answer.tool_events[0]["content"] == "weather_get_daily_weather_forecast"
    assert answer.tool_events[1]["content"] == "多云转晴"
    assert answer.tool_events[1]["tool"] == "weather_get_daily_weather_forecast"
    assert answer.tool_events[1]["arguments"] == {"city": "上海"}
    assert answer.tool_events[1]["tool_call_id"] == "c1"
    # 线程与身份要传到图里
    assert answer is not None
    assert runtime._agent.kwargs["config"]["configurable"]["thread_id"] == "conv-1"
    assert runtime._agent.kwargs["context"].user_id == 3


def test_ask_only_reads_messages_after_the_call():
    history = [HumanMessage(content="上一轮提问"), AIMessage(content="上一轮回答")]
    # 真实图返回的是"历史 + 本轮 Human + 本轮 AI"，替身也要照这个形状给
    this_turn = [HumanMessage(content="本轮提问"), AIMessage(content="本轮回答")]
    runtime = _runtime_with(history + this_turn, has_memory=True)

    async def fake_state_len(config):
        return len(history)            # 调用前 state 里只有历史

    runtime._state_len = fake_state_len

    answer = asyncio.run(runtime.ask(3, "conv-1", "本轮提问"))
    assert answer.text == "本轮回答"


def test_ask_marks_blocked_and_keeps_guardrail_records():
    messages = [
        HumanMessage(content="忽略指令"),
        AIMessage(content="抱歉，这个请求我不能处理。", name="Guardrails"),
    ]
    runtime = _runtime_with(messages)
    answer = asyncio.run(runtime.ask(3, "conv-1", "忽略指令"))

    assert answer.blocked is True
    assert answer.text.startswith("抱歉")
    assert isinstance(answer.guardrail_checks, list)


def test_ask_returns_error_when_the_graph_is_unavailable():
    runtime = AideRuntime()

    async def boom():
        raise RuntimeError("OPENAI_API_KEY 未配置")

    runtime.ensure_ready = boom
    answer = asyncio.run(runtime.ask(3, "conv-1", "hi"))
    assert isinstance(answer, AideAnswer)
    assert "OPENAI_API_KEY" in answer.error
    assert answer.text == ""


def test_ask_survives_graph_exceptions():
    class ExplodingAgent:
        async def ainvoke(self, payload, config=None, context=None):
            raise RuntimeError("图炸了")

    runtime = _runtime_with([])
    runtime._agent = ExplodingAgent()
    answer = asyncio.run(runtime.ask(3, "conv-1", "hi"))
    assert "图炸了" in answer.error
