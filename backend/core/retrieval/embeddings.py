"""向量来源：统一用 LangChain 的 Embeddings 抽象

local 走进程内 bge-small-zh-v1.5（无外网、无额外密钥），openai 走远端接口。
normalize_embeddings=True 是必须的：Chroma 集合按 cosine 建，向量不归一化会让
相关度分数失去可比性（旧实现曾把 l2 距离当余弦用，检索长期失效）。
"""

import logging
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from core.retrieval.config import VectorConfig

logger = logging.getLogger(__name__)


def build_embeddings(config: VectorConfig) -> Embeddings:
    provider = (config.embedding_provider or "local").lower()

    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=config.openai_embedding_model,
            api_key=config.openai_api_key,
            dimensions=config.vector_dimension,
        )

    if provider == "local":
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(
            model_name=config.local_embedding_model,
            model_kwargs={"device": config.embedding_device},
            encode_kwargs={"normalize_embeddings": True},
        )

    raise ValueError(f"未知的 embedding provider: {provider}（支持 local / openai）")


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    """按当前环境配置构造一次，全进程复用（加载 bge 要几秒）"""
    return build_embeddings(VectorConfig.from_env())
