"""向量来源工厂：local 走本地 bge，openai 走远端接口

Embeddings 统一由 LangChain 抽象提供，检索层不再自己调 sentence-transformers。
"""

import pytest

from core.retrieval.embeddings import build_embeddings
from core.retrieval.config import VectorConfig


def test_local_provider_uses_huggingface_embeddings():
    from conftest import LOCAL_MODEL_DIR, local_embedding_available

    if not local_embedding_available():
        pytest.skip(f"缺少本地 embedding 模型 {LOCAL_MODEL_DIR}")

    from langchain_huggingface import HuggingFaceEmbeddings

    config = VectorConfig.from_env().model_copy(update={
        "embedding_provider": "local", "local_embedding_model": LOCAL_MODEL_DIR,
        "embedding_device": "cpu"})
    emb = build_embeddings(config)

    assert isinstance(emb, HuggingFaceEmbeddings)
    assert len(emb.embed_query("你好")) == config.vector_dimension


def test_openai_provider_uses_openai_embeddings():
    from langchain_openai import OpenAIEmbeddings

    config = VectorConfig.from_env().model_copy(update={
        "embedding_provider": "openai", "openai_api_key": "sk-test",
        "openai_embedding_model": "text-embedding-3-small", "vector_dimension": 1536})
    assert isinstance(build_embeddings(config), OpenAIEmbeddings)


def test_unknown_provider_raises_valueerror():
    config = VectorConfig.from_env().model_copy(update={"embedding_provider": "bogus"})
    with pytest.raises(ValueError, match="embedding provider"):
        build_embeddings(config)


def test_env_is_loaded_without_caller_importing_it():
    """检索层必须自己加载 backend/.env

    只靠别的模块顺带 load_dotenv，会让导入顺序决定配置是否可见：顺序不对时
    local_embedding_model 退回数据类默认的 HF hub 模型名，离线机器上变成
    五次网络重试的长时间挂起（实测踩过）。
    """
    import os

    from core.retrieval import config as config_module

    assert os.getenv("LOCAL_EMBEDDING_MODEL"), "core.retrieval.config 导入后应已读到 backend/.env"
    assert config_module.__file__.endswith("config.py")


def test_missing_local_model_dir_fails_fast_instead_of_reaching_the_hub(tmp_path):
    """配置写的是本地目录却不存在时，直接报错，不去连 huggingface.co"""
    config = VectorConfig.from_env().model_copy(update={
        "embedding_provider": "local",
        "local_embedding_model": str(tmp_path / "no-such-model")})

    with pytest.raises(ValueError, match="本地向量模型"):
        build_embeddings(config)
