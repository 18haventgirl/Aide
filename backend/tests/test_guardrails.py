"""输入护栏的辅助逻辑（不调用真实模型）"""

from agents import InputGuardrail
from agents.model_settings import ModelSettings

from agent.guardrails import (
    IRRELEVANT,
    RELEVANCE_GUARDRAIL_NAME,
    RELEVANT,
    SAFETY_GUARDRAIL_NAME,
    SAFE,
    UNSAFE,
    _parse_verdict,
    _record,
    _to_text,
    build_input_guardrails,
)


def test_parse_verdict_accepts_the_agreed_two_line_format():
    assert _parse_verdict("SAFE\n消息正常", SAFE, UNSAFE) == (True, "消息正常")
    assert _parse_verdict("UNSAFE\n包含注入指令", SAFE, UNSAFE) == (False, "包含注入指令")
    assert _parse_verdict("IRRELEVANT.\n与日常助手无关", RELEVANT, IRRELEVANT) == (
        False,
        "与日常助手无关",
    )


def test_parse_verdict_tolerates_markdown_and_extra_words():
    assert _parse_verdict("**SAFE** — 这是 Markdown 包裹", SAFE, UNSAFE)[0] is True
    assert _parse_verdict("UNSAFE 因为越狱", SAFE, UNSAFE)[0] is False


def test_parse_verdict_fails_open_on_garbage():
    passed, reasoning = _parse_verdict("我不知道", SAFE, UNSAFE)

    assert passed is True
    assert "无法识别" in reasoning


def test_parse_verdict_fails_open_on_empty_output():
    assert _parse_verdict("", SAFE, UNSAFE) == (True, "判定结果为空，已放行")


class _FakeContext:
    """最像 RunContextWrapper 的替身：只暴露 .context"""

    def __init__(self, checks):
        self.context = type("Ctx", (), {"guardrail_checks": checks})()


def test_to_text_passes_through_strings():
    assert _to_text("今天天气怎么样") == "今天天气怎么样"


def test_to_text_flattens_response_items():
    items = [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "推荐个菜谱"}],
        }
    ]

    assert "推荐个菜谱" in _to_text(items)


def test_to_text_reads_websocket_session_items():
    """WebSocket 层传入的历史条目只有 role + 字符串 content，没有 type 字段"""
    items = [
        {"role": "user", "content": "明天北京天气怎么样"},
        {"role": "assistant", "content": "北京明天晴，24度"},
        {"role": "user", "content": "那上海呢"},
    ]

    assert _to_text(items) == "那上海呢"


def test_to_text_returns_empty_without_user_message():
    assert _to_text([{"role": "assistant", "content": "你好"}]) == ""


def test_to_text_returns_empty_for_unparsable_input():
    assert _to_text(object()) == ""


def test_record_appends_check_and_truncates_input():
    checks = []

    _record(_FakeContext(checks), SAFETY_GUARDRAIL_NAME, "x" * 500, "理由", False)

    assert len(checks) == 1
    recorded = checks[0]
    assert recorded["name"] == SAFETY_GUARDRAIL_NAME
    assert recorded["passed"] is False
    assert recorded["reasoning"] == "理由"
    assert len(recorded["input"]) == 200


def test_record_is_noop_when_context_has_no_list():
    context = type("Ctx", (), {})()

    _record(type("W", (), {"context": context})(), "Any", "in", "reason", True)

    assert not hasattr(context, "guardrail_checks")


def test_guardrail_names_match_what_agents_list_reports():
    guardrails = build_input_guardrails(None, ModelSettings())

    assert all(isinstance(g, InputGuardrail) for g in guardrails)
    # 名字必须与回传给前端的检查记录一致，否则护栏面板会把它过滤掉
    assert [g.name for g in guardrails] == [SAFETY_GUARDRAIL_NAME, RELEVANCE_GUARDRAIL_NAME]
    assert all(callable(g.guardrail_function) for g in guardrails)
