"""笔记服务的向量索引路径：写入/更新/删除/检索都走 langchain-chroma

REST 契约（note_id/title/tag/score/text）由 _search_rows 一处保证，
所以测试直接打这一层，不去碰 MySQL。
"""

from types import SimpleNamespace

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

import core.retrieval.store as store_mod


class ConstEmbeddings(Embeddings):
    """固定方向向量：任意两条文本的余弦相关度恒为 1.0

    这里只验"REST 形状 + 阈值过滤 + upsert 行为"，语义质量由 test_rag_recall
    用真实 bge 模型把门，随机假向量会让相关度变成负数、断言失去意义。
    """

    def embed_documents(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0, 0.0]


@pytest.fixture(autouse=True)
def fake_vectors(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "_embeddings", lambda: ConstEmbeddings())
    monkeypatch.setattr(store_mod, "_persist_dir", lambda: str(tmp_path / "chroma"))
    monkeypatch.setattr(store_mod, "_prefix", lambda: "lg_aide_test")
    monkeypatch.setattr(store_mod, "_mode", lambda: "local")
    store_mod._stores.clear()
    yield
    store_mod._stores.clear()


def _service():
    """绕开 __init__（它会连 MySQL），只装向量路径需要的字段"""
    from service.services.note_service import NoteService

    service = NoteService.__new__(NoteService)
    service.vector_config = SimpleNamespace(similarity_threshold=0.0)
    return service


def _note(**kw):
    base = dict(id=11, user_id=1, title="番茄炒蛋", content="先炒蛋再放番茄", tag="菜谱",
                status="active")
    base.update(kw)
    return SimpleNamespace(**base)


def test_service_no_longer_holds_a_vector_client():
    import inspect

    from service.services.note_service import NoteService

    assert "vector_client" not in inspect.signature(NoteService.__init__).parameters
    assert not hasattr(_service(), "vector_client")


def test_index_then_update_then_delete_on_one_collection():
    service = _service()
    store = store_mod.note_store(1)

    service._index_note(_note())
    assert store.get()["ids"] == ["note_11"]
    assert store.similarity_search("番茄炒蛋", k=1)[0].metadata["note_id"] == "11"

    service._index_note(_note(title="猫砂采购", content="宠物店买猫砂"))
    assert len(store.get()["ids"]) == 1                    # 覆盖，不是新增第二条
    assert store.get()["metadatas"][0]["title"] == "猫砂采购"

    service._drop_index(1, 11)
    assert store.get()["ids"] == []


def test_empty_content_is_not_indexed():
    """与迁移前一致：没有正文的笔记不进索引，避免空文档污染检索结果"""
    service = _service()
    service._index_note(_note(content=""))
    assert store_mod.note_store(1).get()["ids"] == []


def test_vector_store_failure_does_not_break_the_database_write(monkeypatch):
    service = _service()
    monkeypatch.setattr("service.services.note_service.note_store",
                        lambda uid: (_ for _ in ()).throw(RuntimeError("chroma 挂了")))

    service._index_note(_note())        # 不抛异常即为通过：MySQL 已提交，索引只是尽力而为
    service._drop_index(1, 11)


def test_search_rows_emit_rest_contract_keys_and_honour_threshold():
    from service.services.note_service import _search_rows

    store = store_mod.note_store(1)
    store.add_documents([Document(
        page_content="阳台绿萝\n土表发白就浇透", id="note_1",
        metadata={"note_id": "1", "title": "阳台绿萝", "tag": "园艺"})])

    rows = _search_rows(store, "绿萝浇水", threshold=0.0, limit=3)
    assert sorted(rows[0]) == ["note_id", "score", "tag", "text", "title"]
    assert rows[0]["note_id"] == "1" and rows[0]["tag"] == "园艺"
    assert rows[0]["score"] == pytest.approx(1.0)        # 固定向量 → 相关度恒为 1

    assert _search_rows(store, "绿萝浇水", threshold=1.1, limit=3) == []


def test_search_notes_by_vector_returns_empty_when_config_missing():
    service = _service()
    service.vector_config = None
    assert service.search_notes_by_vector(1, "绿萝") == []
