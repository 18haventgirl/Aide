"""向量来源工厂：local 走本地 bge，openai 走远端接口

Embeddings 统一由 LangChain 抽象提供，检索层不再自己调 sentence-transformers。
"""

import pytest

from core.retrieval.embeddings import build_embeddings
from core.vector_core.config import VectorConfig


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
