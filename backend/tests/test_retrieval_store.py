"""向量库工厂：集合命名、按用户隔离、cosine 空间、文档映射与 REST 键

隔离靠集合命名空间而不是 where 过滤：过滤条件一旦在某处漏传就是跨用户读取。
"""

import logging
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

import core.retrieval.store as store_mod
from core.retrieval.documents import documents_to_rows, note_document
from core.retrieval.store import collection_name, note_store, vector_health


@pytest.fixture
def fake_store(tmp_path, monkeypatch):
    """确定性假向量：不加载 bge 模型，也不碰 backend/lg-aide-chroma-db"""
    monkeypatch.setattr(store_mod, "_embeddings", lambda: DeterministicFakeEmbedding(size=64))
    monkeypatch.setattr(store_mod, "_persist_dir", lambda: str(tmp_path / "chroma"))
    monkeypatch.setattr(store_mod, "_prefix", lambda: "lg_aide_test")
    monkeypatch.setattr(store_mod, "_mode", lambda: "local")
    store_mod._stores.clear()
    yield note_store
    store_mod._stores.clear()


def test_collection_name_is_sanitized_and_prefixed():
    assert collection_name("lg_aide", 12) == "lg_aide_user_12"
    assert collection_name("lg_aide", "a-b.c") == "lg_aide_user_a_b_c"


def test_each_user_gets_a_separate_collection(fake_store):
    a, b = fake_store(1), fake_store(2)

    assert a._collection.name == "lg_aide_test_user_1"
    assert b._collection.name == "lg_aide_test_user_2"
    assert fake_store(1) is a          # 同一用户复用实例，不重复建集合


def test_cosine_space_is_declared_on_creation(fake_store):
    assert fake_store(1)._collection.metadata["hnsw:space"] == "cosine"


def test_note_document_keeps_existing_id_and_metadata_contract():
    note = SimpleNamespace(id=7, user_id=1, title="阳台绿萝浇水", content="土表发白就浇透",
                           tag="园艺", status="active")
    doc = note_document(note)

    assert doc.id == "note_7"
    assert doc.page_content == "阳台绿萝浇水\n土表发白就浇透"
    assert doc.metadata == {"note_id": "7", "user_id": "1", "title": "阳台绿萝浇水",
                            "tag": "园艺", "status": "active", "source": "notes"}


def test_note_document_tolerates_missing_content_and_tag():
    doc = note_document(SimpleNamespace(id=8, user_id=1, title="只有标题", content=None,
                                        tag=None, status=None))
    assert doc.page_content == "只有标题\n"
    assert doc.metadata["tag"] == "" and doc.metadata["status"] == ""


def test_documents_to_rows_emits_rest_contract_keys_and_filters_threshold():
    pairs = [(Document(page_content="a\nb", metadata={"note_id": "1", "title": "a", "tag": "t"}), 0.81),
             (Document(page_content="c", metadata={"note_id": "2", "title": "c", "tag": ""}), 0.12)]
    rows = documents_to_rows(pairs, threshold=0.3)

    assert len(rows) == 1
    assert sorted(rows[0]) == ["note_id", "score", "tag", "text", "title"]
    assert rows[0]["note_id"] == "1"
    assert rows[0]["text"] == "a\nb" and abs(rows[0]["score"] - 0.81) < 1e-9


def test_empty_tag_becomes_none_for_rest_shape():
    rows = documents_to_rows(
        [(Document(page_content="x", metadata={"note_id": "3", "title": "x", "tag": ""}), 0.9)],
        threshold=0.0)
    assert rows[0]["tag"] is None


def test_vector_health_reports_collection_count(fake_store):
    fake_store(1)
    health = vector_health()

    assert health["status"] == "healthy" and health["collections"] >= 1


def test_http_mode_is_warned_once(fake_store, monkeypatch, caplog):
    """检索层只走本地持久化；配了 http 必须说清楚，别让人以为数据在 8101"""
    monkeypatch.setattr(store_mod, "_mode", lambda: "http")
    store_mod._http_warned = False

    with caplog.at_level(logging.WARNING):
        fake_store(7)
        fake_store(8)

    warnings = [r for r in caplog.records if "CHROMA_CLIENT_MODE" in r.getMessage()]
    assert len(warnings) == 1
