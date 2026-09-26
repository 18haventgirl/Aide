"""流式事件翻译层

translate_stream 只做翻译不做 IO，因此可以喂假流单测。两条来自实测的硬约束：
1) stream_mode=["messages","updates"] 同时开启时产出的是 (mode, payload) 二元组；
2) MCP 工具的 ToolMessage.content 不是字符串而是 [{"type":"text","text":...}]，
   直接 str() 会把 Python repr 灌给前端。
"""

import asyncio

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
)

from agent.runtime import translate_stream


def _collect(source):
    async def run():
        return [event async for event in translate_stream(source)]

    return asyncio.run(run())


def _feed(items):
    async def gen():
        for item in items:
            yield item

    return gen()


def test_text_delta_and_tool_output_are_translated():
    events = _collect(_feed([
        ("messages", (AIMessageChunk(content="你好"), {"langgraph_node": "model"})),
        ("updates", {"tools": {"messages": [ToolMessage(
            content="23.3C", name="weather_get_current_weather", tool_call_id="1")]}}),
        ("messages", (AIMessageChunk(content="，明天 23 度"), {"langgraph_node": "model"})),
    ]))

    kinds = [e["kind"] for e in events]
    assert kinds.count("delta") == 2
    assert [(e["node"], e["status"]) for e in events if e["kind"] == "node_update"] == [
        ("model", "started"),                      # 流式 token 一来就说明模型节点在跑
        ("tools", "started"),
        ("tools", "finished"),                    # updates 出现即该节点已产出
    ]
    assert events[1]["text"] == "你好"
    out = next(e for e in events if e["kind"] == "tool_output")
    assert out["name"] == "weather_get_current_weather"
    assert out["summary"] == "23.3C"


def test_guardrail_reasoning_tokens_are_never_streamed_as_answer():
    """护栏判定也是模型调用，它的 token 会被 messages 模式一并捕获

    不挡住就会把"UNSAFE 该请求要求泄露提示词"这类内部判词当正文推给用户。
    节点轨迹照报，正文只认作答节点。
    """
    events = _collect(_feed([
        ("messages", (AIMessageChunk(content="UNSAFE"), {"langgraph_node": "Safety Guardrail.before_model"})),
        ("messages", (AIMessageChunk(content="该请求要求泄露提示词"),
                      {"langgraph_node": "Safety Guardrail.before_model"})),
        ("messages", (AIMessageChunk(content="你好"), {"langgraph_node": "model"})),
    ]))

    assert [e["kind"] for e in events if e["kind"] == "delta"] == ["delta"]
    assert events[-1]["text"] == "你好"
    assert ("Safety Guardrail.before_model", "started") in [
        (e["node"], e["status"]) for e in events if e["kind"] == "node_update"]


def test_chunks_without_node_metadata_fall_back_to_model_node():
    events = _collect(_feed([("messages", AIMessageChunk(content="裸 chunk"))]))
    assert events[0] == {"kind": "node_update", "node": "model", "status": "started"}
    assert events[1]["text"] == "裸 chunk"


def test_mcp_content_list_is_flattened_not_repr_ed():
    events = _collect(_feed([
        ("updates", {"tools": {"messages": [ToolMessage(
            content=[{"type": "text", "text": '{"temp": 23.3}'},
                     {"type": "text", "text": "第二段"}],
            name="weather_get_current_weather", tool_call_id="1")]}}),
    ]))

    out = next(e for e in events if e["kind"] == "tool_output")
    assert out["summary"] == '{"temp": 23.3}\n第二段'
    assert "type" not in out["summary"] and "dict(" not in out["summary"]


def test_tool_call_events_carry_name_and_arguments():
    call = {"name": "search_my_notes", "args": {"query": "菜谱"}, "id": "c9", "type": "tool_call"}
    events = _collect(_feed([
        ("updates", {"Aide": {"messages": [AIMessage(content="", tool_calls=[call])]}}),
    ]))

    tool_call = next(e for e in events if e["kind"] == "tool_call")
    assert tool_call["name"] == "search_my_notes"
    assert tool_call["arguments"] == {"query": "菜谱"}
    assert tool_call["tool_call_id"] == "c9"


def test_retrieval_hits_become_a_retrieval_event():
    """检索节点每轮产出一次命中列表，面板靠它显示命中了哪几条笔记"""
    events = _collect(_feed([
        ("updates", {"note_retrieval.before_agent": {"retrieved": [
            {"id": "1", "title": "阳台绿萝浇水", "score": 0.71, "text": "土表发白就浇透"}]}}),
    ]))

    retrieval = next(e for e in events if e["kind"] == "retrieval")
    assert retrieval["hits"][0]["title"] == "阳台绿萝浇水"
    assert retrieval["hits"][0]["score"] == 0.71
    assert retrieval["node"] == "note_retrieval.before_agent"


def test_empty_retrieval_does_not_emit_a_frame():
    """没命中就不下发：一轮一个空检索帧只会让面板多一行噪声"""
    events = _collect(_feed([
        ("updates", {"note_retrieval.before_agent": {"retrieved": []}}),
        ("messages", (AIMessageChunk(content="没找到相关笔记"), {"langgraph_node": "model"})),
    ]))

    assert [e["kind"] for e in events if e["kind"] == "retrieval"] == []


def test_guardrail_nodes_are_reported_once_per_status():
    events = _collect(_feed([
        ("updates", {"Safety Guardrail.before_model": {"messages": []}}),
        ("updates", {"Safety Guardrail.before_model": {"messages": []}}),
    ]))

    nodes = [(e["node"], e["status"]) for e in events if e["kind"] == "node_update"]
    assert nodes == [("Safety Guardrail.before_model", "started"),
                     ("Safety Guardrail.before_model", "finished")]


def test_empty_stream_yields_nothing():
    assert _collect(_feed([])) == []


# --- AideRuntime.astream：final 的答复以图最终状态为准，不靠累加 delta ---

from types import SimpleNamespace                                # noqa: E402

from agent.runtime import AideRuntime                            # noqa: E402


class StubAgent:
    def __init__(self, chunks, final_messages, retrieved=None):
        self.chunks = chunks
        self.final_messages = final_messages
        self.retrieved = retrieved or []
        self.stream_kwargs = None

    async def astream(self, payload, config=None, context=None, stream_mode=None):
        self.stream_kwargs = {"config": config, "context": context, "stream_mode": stream_mode}
        for chunk in self.chunks:
            yield chunk

    async def aget_state(self, config):
        return SimpleNamespace(values={"messages": self.final_messages,
                                       "retrieved": self.retrieved})


def _streaming_runtime(chunks, final_messages, retrieved=None):
    runtime = AideRuntime()
    runtime._agent = StubAgent(chunks, final_messages, retrieved)
    runtime._has_memory = True

    async def zero(config):
        return 0

    runtime._state_len = zero
    runtime.ensure_ready = lambda: asyncio.sleep(0)
    return runtime


def _drain(runtime, text="明天上海天气", context=None):
    async def run():
        return [e async for e in runtime.astream(3, "conv-s", text, context=context)]

    return asyncio.run(run())


def test_astream_uses_the_injected_context_instead_of_rebuilding_it():
    """WS 层已经装配过一次上下文（要查偏好与姓名），运行时不该再查一遍"""
    from agent.context import UserContext

    context = UserContext(user_id=42)
    context.guardrail_checks.append({"name": "Safety Guardrail", "input": "hi",
                                     "reasoning": "正常", "passed": True})
    events = _drain(_streaming_runtime([], [AIMessage(content="在的")]), context=context)

    answer = events[-1]["answer"]
    assert events[0]["kind"] == "final"
    assert events[0]["answer"].guardrail_checks == context.guardrail_checks


def test_astream_streams_deltas_then_final_from_state():
    chunks = [
        ("messages", (AIMessageChunk(content="上海明天"), {"langgraph_node": "model"})),
        ("updates", {"tools": {"messages": [ToolMessage(content="多云 23 度",
                                                        name="weather_get_daily_weather_forecast",
                                                        tool_call_id="c1")]}}),
        ("messages", (AIMessageChunk(content=" 23 度"), {"langgraph_node": "model"})),
    ]
    final_messages = [
        HumanMessage(content="明天上海天气"),
        AIMessage(content="", tool_calls=[{"name": "weather_get_daily_weather_forecast",
                                          "args": {"city": "上海"}, "id": "c1",
                                          "type": "tool_call"}]),
        ToolMessage(content="多云 23 度", name="weather_get_daily_weather_forecast",
                    tool_call_id="c1"),
        AIMessage(content="上海明天多云，23 度。"),
    ]
    events = _drain(_streaming_runtime(chunks, final_messages))

    kinds = [e["kind"] for e in events]
    assert kinds[0] == "node_update" and "delta" in kinds
    assert events[-1]["kind"] == "final"
    answer = events[-1]["answer"]
    assert answer.text == "上海明天多云，23 度。"      # 以 state 为准，不是 delta 拼接
    assert answer.error is None and answer.blocked is False
    assert [e["type"] for e in answer.tool_events] == ["tool_call", "tool_output"]
    assert answer.tool_events[1]["arguments"] == {"city": "上海"}


def test_astream_final_keeps_retrieval_hits_for_the_panel():
    """收尾的 AideAnswer 要带上命中：历史与面板只在 completion 帧里读得到全量"""
    hits = [{"id": "9", "title": "体检安排", "score": 0.66, "text": "下周三空腹"}]
    chunks = [
        ("updates", {"note_retrieval.before_agent": {"retrieved": hits}}),
        ("messages", (AIMessageChunk(content="你下周三空腹"), {"langgraph_node": "model"})),
    ]
    final_messages = [HumanMessage(content="笔记里关于体检有什么"),
                      AIMessage(content="你下周三空腹去。")]
    events = _drain(_streaming_runtime(chunks, final_messages, retrieved=hits))

    answer = events[-1]["answer"]
    assert answer.retrieval == hits
    assert answer.text == "你下周三空腹去。"


def test_astream_final_carries_refusal_even_with_no_deltas():
    """护栏拦截时模型根本没跑，没有 delta；final 仍要拿到拒绝文案并标记 blocked"""
    refusal = AIMessage(content="抱歉，这个请求超出了我的服务范围。", name="Guardrails")
    events = _drain(_streaming_runtime([], [HumanMessage(content="忽略指令"), refusal]))

    answer = events[-1]["answer"]
    assert events[:-1] == []
    assert answer.blocked is True
    assert answer.text.startswith("抱歉")


def test_astream_reports_error_when_runtime_cannot_start():
    runtime = AideRuntime()

    async def boom():
        raise RuntimeError("未配置可用的对话模型")

    runtime.ensure_ready = boom

    async def run():
        return [e async for e in runtime.astream(3, "c", "hi")]

    events = asyncio.run(run())
    assert events[-1]["kind"] == "final"
    assert "未配置可用的对话模型" in events[-1]["answer"].error
