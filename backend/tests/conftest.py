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


@pytest.fixture
def rag_client(tmp_path):
    """指向临时目录的独立 Chroma + 本地向量模型，避免污染 backend/lg-aide-chroma-db

    模型没下载时直接 skip（向量检索必须有 embedding 来源，用远端 OpenAI 会让测试依赖外网）。
    """
    if not local_embedding_available():
        pytest.skip(f"缺少本地 embedding 模型 {LOCAL_MODEL_DIR}，按 README「5.1 本地向量化」下载后重跑")

    from core.vector_core.client import ChromaVectorClient
    from core.vector_core.config import VectorConfig

    config = VectorConfig.from_env().model_copy(update={
        "chroma_client_mode": "local",
        "chroma_persist_directory": str(tmp_path / "chroma"),
        "chroma_collection_prefix": "lg_aide_test",
        "embedding_provider": "local",
        "local_embedding_model": LOCAL_MODEL_DIR,
        "similarity_threshold": 0.3,
    })
    return ChromaVectorClient(config)
