"""重建脚本必须幂等，且只影响指定用户

换 embedding 模型或改文档布局时要能整体重算索引；跑两次不能翻倍，
也不能把别的用户的集合碰坏。
"""

from types import SimpleNamespace

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

import core.retrieval.store as store_mod
from scripts.reindex_notes import reindex_user


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "_embeddings", lambda: DeterministicFakeEmbedding(size=64))
    monkeypatch.setattr(store_mod, "_persist_dir", lambda: str(tmp_path / "chroma"))
    monkeypatch.setattr(store_mod, "_prefix", lambda: "lg_aide_test")
    monkeypatch.setattr(store_mod, "_mode", lambda: "local")
    store_mod._stores.clear()
    yield store_mod.note_store(5)
    store_mod._stores.clear()


def _notes(user_id=5, count=3):
    return [SimpleNamespace(id=i, user_id=user_id, title=f"笔记{i}", content=f"内容{i}",
                            tag="t", status="active") for i in range(1, count + 1)]


def test_reindex_writes_every_note(store):
    assert reindex_user(5, _notes()) == 3
    assert len(store.get()["ids"]) == 3


def test_reindex_is_idempotent(store):
    reindex_user(5, _notes())
    assert reindex_user(5, _notes()) == 3          # 第二次不翻倍
    assert len(store.get()["ids"]) == 3


def test_reindex_drops_stale_documents(store):
    reindex_user(5, _notes(count=3))
    reindex_user(5, _notes(count=1))               # 库里只剩一条笔记
    assert len(store.get()["ids"]) == 1


def test_reindex_skips_notes_without_content(store):
    notes = _notes(count=2) + [SimpleNamespace(id=99, user_id=5, title="空笔记", content="",
                                               tag="", status="active")]
    assert reindex_user(5, notes) == 2
    assert len(store.get()["ids"]) == 2


def test_reindex_leaves_other_users_untouched(store, tmp_path):
    reindex_user(5, _notes())
    other = store_mod.note_store(6)
    reindex_user(5, _notes(count=1))
    assert other.get()["ids"] == []                # 别的用户没被清
