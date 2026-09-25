"""WebSocket 协议映射

旧引擎每个 token 都下发一份完整的 ChatResponse（raw_response 越攒越长，一帧比一帧大）。
新引擎把过程帧改成小载荷（delta / node_update / tool_call / tool_output / tools_list），
只有最后的 completion 帧沿用 ChatResponse 形状，前端历史与面板的读取方式不变。
"""

import asyncio

from core.web_socket_core import MessageType

from api.ws_stream import WsStreamTranslator


def _translator(**kw):
    defaults = dict(user_id="3", connection_id="c1", conversation_id="conv1",
                    context={"user_id": 3}, tools_manifest=[
                        {"name": "search_my_notes", "description": "语义检索我的笔记"},
                        {"name": "weather_get_current_weather", "description": "当前天气"},
                    ])
    defaults.update(kw)
    return WsStreamTranslator(**defaults)


def _feed(*events):
    async def run():
        translator = _translator()
        return translator, [await translator.feed(e) for e in events]

    return asyncio.run(run())


def test_delta_frame_is_incremental_and_light():
    translator, (msg,) = _feed({"kind": "delta", "text": "上海", "node": "model"})

    content = msg.content
    assert content["type"] == "delta"
    assert content["delta"] == "上海"
    assert content["text_so_far"] == "上海"
    assert "raw_response" not in content          # 不再每帧塞整份 ChatResponse
    assert msg.type == MessageType.AI_RESPONSE
    assert msg.room_id == "user_3_room"
    assert msg.sender_id == "system"


def test_tool_call_and_tool_output_are_forwarded():
    _, (call, out) = _feed(
        {"kind": "tool_call", "name": "weather_get_current_weather",
         "arguments": {"city": "上海"}, "tool_call_id": "c1", "node": "model"},
        {"kind": "tool_output", "name": "weather_get_current_weather",
         "summary": "23.3C", "tool_call_id": "c1", "node": "tools"},
    )

    assert call.content["type"] == "tool_call"
    assert call.content["tool"] == "weather_get_current_weather"
    assert call.content["arguments"] == {"city": "上海"}
    assert out.content["type"] == "tool_output"
    assert out.content["summary"] == "23.3C"


def test_node_update_is_forwarded_and_guardrail_nodes_kept():
    _, (msg,) = _feed({"kind": "node_update", "node": "Safety Guardrail.before_model",
                       "status": "started"})

    assert msg.content["type"] == "node_update"
    assert msg.content["node"] == "Safety Guardrail.before_model"
    assert msg.content["status"] == "started"


def test_final_kind_is_not_a_process_frame():
    """final 由 completion_message 单独下发，feed 必须返回 None 以免重复"""
    from agent.runtime import AideAnswer

    _, (msg,) = _feed({"kind": "final", "answer": AideAnswer(text="x")})
    assert msg is None


def test_unknown_kind_is_dropped():
    _, (msg,) = _feed({"kind": "something-new"})
    assert msg is None


def test_tools_list_frame_announces_single_agent_and_tools():
    translator = _translator()
    content = translator.tools_list_message().content

    assert content["type"] == "tools_list"
    assert [a["name"] for a in content["agents"]] == ["Aide"]
    assert content["agents"][0]["tools"] == ["search_my_notes", "weather_get_current_weather"]
    assert content["tools"][0]["name"] == "search_my_notes"


def test_completion_keeps_legacy_chat_response_shape():
    from agent.runtime import AideAnswer

    translator = _translator()
    answer = AideAnswer(
        text="上海明天 23 度",
        tool_events=[
            {"type": "tool_call", "tool": "weather_get_current_weather",
             "arguments": {"city": "上海"}, "content": "weather_get_current_weather",
             "tool_call_id": "c1"},
            {"type": "tool_output", "tool": "weather_get_current_weather",
             "content": "23.3C", "arguments": {}, "tool_call_id": "c1"},
        ],
        guardrail_checks=[
            {"name": "Safety Guardrail", "input": "明天上海天气", "reasoning": "正常", "passed": True}],
    )
    message = translator.completion_message(answer)
    payload = message.content["final_response"]

    assert message.content["type"] == "completion"
    assert payload["raw_response"] == "上海明天 23 度"
    assert payload["is_finished"] is True and payload["is_error"] is False
    assert payload["current_agent"] == "Aide"
    assert payload["conversation_id"] == "conv1"
    assert payload["guardrails"][0]["name"] == "Safety Guardrail"
    assert payload["guardrails"][0]["passed"] is True
    assert [e["type"] for e in payload["events"]] == ["tool_call", "tool_output"]
    assert payload["messages"][-1]["content"] == "上海明天 23 度"
    assert payload["messages"][-1]["agent"] == "Aide"
    assert payload["tools"][0]["name"] == "search_my_notes"
    assert message.content["message"] == "对话完成"


def test_blocked_answer_is_reported_without_error():
    from agent.runtime import AideAnswer

    translator = _translator()
    answer = AideAnswer(
        text="抱歉，这个请求超出了我的服务范围。",
        guardrail_checks=[{"name": "Relevance Guardrail", "input": "破解wifi",
                           "reasoning": "超出范围", "passed": False}],
        blocked=True,
    )
    payload = translator.completion_message(answer).content

    assert payload["message"] == "输入被护栏拦截"
    response = payload["final_response"]
    assert response["is_error"] is False
    assert response["messages"][-1]["agent"] == "Guardrails"
    assert response["guardrails"][0]["passed"] is False


def test_error_answer_marks_is_error_and_keeps_guardrails():
    from agent.runtime import AideAnswer

    translator = _translator()
    answer = AideAnswer(error="未配置可用的对话模型",
                        guardrail_checks=[{"name": "Safety Guardrail", "input": "hi",
                                           "reasoning": "正常", "passed": True}])
    envelope = translator.completion_message(answer).content
    response = envelope["final_response"]

    assert response["is_error"] is True
    assert response["error_message"] == "未配置可用的对话模型"
    assert response["raw_response"] == ""
    assert envelope["message"] == "处理过程中发生错误"
    assert len(response["guardrails"]) == 1
