"""模型名兼容与 LangChain 模型构造"""

from agent.model import build_chat_model, resolve_model_name


def test_strips_litellm_provider_prefix():
    assert resolve_model_name("openai/deepseek-chat") == "deepseek-chat"


def test_keeps_plain_model_name():
    assert resolve_model_name("deepseek-chat") == "deepseek-chat"


def test_only_strips_provider_segment():
    # 只剥第一段 provider，模型名自身含斜杠时保留
    assert resolve_model_name("openai/org/model-x") == "org/model-x"


def test_handles_empty_value():
    assert resolve_model_name("") == ""
    assert resolve_model_name(None) == ""


def test_build_chat_model_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert build_chat_model() is None
