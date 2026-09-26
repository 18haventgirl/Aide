"""前置检索：每轮一次，结果进 state.retrieved，注入但不落历史

放在 before_agent 而不是 before_model，是为了工具回环不再重复检索；
注入走 wrap_model_call，是因为写进 messages 的内容会被 checkpoint 永久保留，
多轮下来历史里会堆满检索片段。
"""

import asyncio

import pytest
from langchain.agents import create_agent
from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.messages import AIMessage, HumanMessage

import core.retrieval.store as store_mod
from agent.context import UserContext
from agent.retrieval import build_retrieval_injector, build_retrieval_middleware
from agent.state import AideState


class StubModel(BaseChatModel):
    """按脚本作答的替身模型（必须是 BaseChatModel：create_agent 会调 model.bind）"""

    reply: str = "好的"
    seen: list = []

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "stub"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return ChatResult(generations=[
            ChatGeneration(message=AIMessage(content=self.reply))])


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "_embeddings", lambda: DeterministicFakeEmbedding(size=64))
    monkeypatch.setattr(store_mod, "_persist_dir", lambda: str(tmp_path / "chroma"))
    monkeypatch.setattr(store_mod, "_prefix", lambda: "lg_aide_test")
    monkeypatch.setattr(store_mod, "_mode", lambda: "local")
    store_mod._stores.clear()
    handle = store_mod.note_store(3)
    handle.add_documents([
        Document(page_content="阳台绿萝浇水\n土表发白就浇透，冬天两周一次", id="note_1",
                 metadata={"note_id": "1", "title": "阳台绿萝浇水", "tag": "园艺"}),
    ])
    yield handle
    store_mod._stores.clear()


def _run(model, middlewares, text="我的绿萝多久浇一次水"):
    async def go():
        agent = create_agent(model, [], middleware=middlewares,
                             state_schema=AideState, context_schema=UserContext, name="Aide")
        return await agent.ainvoke({"messages": [HumanMessage(content=text)]},
                                   context=UserContext(user_id=3))

    return asyncio.run(go())


def test_retrieval_runs_once_and_fills_state(store):
    state = _run(StubModel(), [build_retrieval_middleware(k=3, threshold=0.0)])

    hits = state["retrieved"]
    assert len(hits) == 1
    assert hits[0]["title"] == "阳台绿萝浇水"
    assert hits[0]["text"].startswith("阳台绿萝浇水")
    assert isinstance(hits[0]["score"], float)


def test_retrieval_does_not_add_messages(store):
    state = _run(StubModel(), [build_retrieval_middleware(k=3, threshold=0.0)])

    assert [type(m).__name__ for m in state["messages"]] == ["HumanMessage", "AIMessage"]


def test_retrieval_degrades_to_no_hits_when_store_is_broken(store, monkeypatch):
    def boom(uid):
        raise RuntimeError("chroma 挂了")

    monkeypatch.setattr(store_mod, "note_store", boom)
    state = _run(StubModel(), [build_retrieval_middleware(k=3, threshold=0.0)])

    assert state["retrieved"] == []          # 检索挂了不影响回答


def test_threshold_filters_everything(store):
    state = _run(StubModel(), [build_retrieval_middleware(k=3, threshold=1.5)])
    assert state["retrieved"] == []


def test_injector_shows_hits_to_the_model_but_not_in_state(store):
    model = StubModel(reply="两周一次", seen=[])
    state = _run(model, [build_retrieval_middleware(k=3, threshold=0.0),
                         build_retrieval_injector()])

    seen = model.seen[0]
    assert any("笔记检索结果" in str(m.content) for m in seen)              # 模型看到了
    assert not any("笔记检索结果" in str(m.content) for m in state["messages"])   # 没落进状态
    assert state["messages"][-1].content == "两周一次"
