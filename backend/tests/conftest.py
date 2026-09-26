"""让 pytest 能从 backend 目录导入 core / agent / service 等顶层包"""

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 测试进程不会自动加载 backend/.env（只有被导入的业务模块会加载），
# 而 embedding provider、CHROMA_* 等配置都依赖它，所以在这里显式补齐
load_dotenv(BACKEND_DIR / ".env")

LOCAL_MODEL_DIR = os.path.join(str(BACKEND_DIR), "models", "bge-small-zh-v1.5")


def local_embedding_available() -> bool:
    """本地向量模型是否已按 README 5.1 下载到工作区"""
    return os.path.isdir(LOCAL_MODEL_DIR)


require_local_embedding = pytest.mark.skipif(
    not local_embedding_available(),
    reason=f"缺少本地 embedding 模型 {LOCAL_MODEL_DIR}，按 README「5.1 本地向量化」下载后重跑",
)


@pytest.fixture(autouse=True)
def fake_retrieval_backend(monkeypatch, tmp_path):
    """默认把笔记向量库换成假向量 + 临时目录

    图一构建就会挂上真实的检索钩子，钩子里又要取 Chroma 句柄；不挡掉的话，任何跑图
    的单测都会加载几百 MB 的本地模型，还可能往真实数据目录里写。需要真向量的测试
    自己再 patch 一次（后申请者生效，如本文件的 rag_store）。
    """
    import core.retrieval.store as store_mod
    from langchain_core.embeddings import DeterministicFakeEmbedding

    monkeypatch.setattr(store_mod, "_embeddings", lambda: DeterministicFakeEmbedding(size=64))
    monkeypatch.setattr(store_mod, "_persist_dir", lambda: str(tmp_path / "chroma-fake"))
    monkeypatch.setattr(store_mod, "_prefix", lambda: "lg_aide_fake")
    monkeypatch.setattr(store_mod, "_mode", lambda: "local")
    store_mod._stores.clear()
    yield store_mod
    store_mod._stores.clear()


@pytest.fixture
def rag_store(tmp_path, monkeypatch):
    """临时目录里的 Chroma 集合 + 本地 bge 向量；模型缺失则 skip

    断言基线（5 语料 / 8 组查询 / 更新反转 / 删除生效）与换成标准件之前完全一致，
    这是"重构没把检索改坏"的唯一判据。
    """
    if not local_embedding_available():
        pytest.skip(f"缺少本地 embedding 模型 {LOCAL_MODEL_DIR}，按 README「5.1 本地向量化」下载后重跑")

    import core.retrieval.store as store_mod

    monkeypatch.setattr(store_mod, "_persist_dir", lambda: str(tmp_path / "chroma"))
    monkeypatch.setattr(store_mod, "_prefix", lambda: "lg_aide_test")
    monkeypatch.setattr(store_mod, "_mode", lambda: "local")
    monkeypatch.setattr(store_mod, "_embeddings", lambda: local_embeddings())
    store_mod._stores.clear()
    yield store_mod.note_store("tester")
    store_mod._stores.clear()


def local_embeddings():
    from langchain_core.embeddings import Embeddings
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=LOCAL_MODEL_DIR,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
