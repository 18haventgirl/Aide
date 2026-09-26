"""向量来源：统一用 LangChain 的 Embeddings 抽象

local 走进程内 bge-small-zh-v1.5（无外网、无额外密钥），openai 走远端接口。
normalize_embeddings=True 是必须的：Chroma 集合按 cosine 建，向量不归一化会让
相关度分数失去可比性（旧实现曾把 l2 距离当余弦用，检索长期失效）。
"""

import logging
import re
from functools import lru_cache
from pathlib import Path

from langchain_core.embeddings import Embeddings

from core.retrieval.config import VectorConfig

logger = logging.getLogger(__name__)

HUB_MODEL_ID = re.compile(r"^[\w.-]+/[\w.-]+$")


def _resolve_local_model(value: str) -> str:
    """本地模型路径校验

    配置写成路径却又不存在时直接报错：sentence-transformers 会把它当成 HF hub
    模型名去联网拉取，离线机器上就是五次重试的长时间挂起（实测踩过）。
    只有形如 org/name 的 hub 模型名才允许走网络。
    """
    looks_like_path = not HUB_MODEL_ID.match(value) or value.startswith((".", "/", "\\"))
    if not looks_like_path:
        return value

    path = Path(value)
    if not path.is_absolute():
        backend_dir = Path(__file__).resolve().parents[2]
        path = (backend_dir / path).resolve()
    if not path.is_dir():
        raise ValueError(
            f"本地向量模型目录不存在：{value}（解析为 {path}）。"
            "请按 README「5.1 本地向量化」下载模型，或把 LOCAL_EMBEDDING_MODEL 改成有效路径")
    return str(path)


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
            model_name=_resolve_local_model(config.local_embedding_model),
            model_kwargs={"device": config.embedding_device},
            encode_kwargs={"normalize_embeddings": True},
        )

    raise ValueError(f"未知的 embedding provider: {provider}（支持 local / openai）")


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    """按当前环境配置构造一次，全进程复用（加载 bge 要几秒）"""
    return build_embeddings(VectorConfig.from_env())
