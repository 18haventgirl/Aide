"""模型名兼容、LangChain 模型构造与会话标题生成"""

import asyncio

from langchain_core.messages import AIMessage

from agent.model import (
    build_chat_model,
    generate_conversation_title,
    resolve_model_name,
)


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


class _StubModel:
    """只关心标题清洗，不测模型行为"""

    def __init__(self, reply=None, raises=False):
        self.reply = reply
        self.raises = raises
        self.seen = None

    async def ainvoke(self, messages):
        self.seen = messages
        if self.raises:
            raise RuntimeError("provider down")
        return AIMessage(content=self.reply)


def _title(model, user_text="明天上海天气怎么样", assistant_text="上海明天多云 23 度"):
    return asyncio.run(generate_conversation_title(user_text, assistant_text, model=model))


def test_title_is_cleaned_of_quotes_and_punctuation():
    assert _title(_StubModel(reply=' "上海天气"。\n')) == "上海天气"


def test_title_is_truncated_to_ten_chars():
    assert len(_title(_StubModel(reply="这是一条长得离谱的会话标题需要被截断"))) <= 10


def test_prompt_carries_both_sides_of_the_dialogue():
    model = _StubModel(reply="天气")
    _title(model)
    prompt = " ".join(str(m.content) for m in model.seen)
    assert "明天上海天气怎么样" in prompt and "上海明天多云 23 度" in prompt


def test_title_returns_none_when_model_fails_or_is_missing():
    assert _title(_StubModel(raises=True)) is None
    assert _title(None) is None
    assert _title(_StubModel(reply="   ")) is None
