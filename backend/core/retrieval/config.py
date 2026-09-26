"""
Vector Database Configuration
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel

# 显式定位 backend/.env：以前只靠其它模块顺带加载，导入顺序不对时
# local_embedding_model 会退回数据类里的 HF hub 模型名，离线机器上变成五次网络重试。
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class VectorConfig(BaseModel):
    """Vector database configuration"""
    
    # Embedding provider: "openai"(远端 API) 或 "local"(进程内本地模型，无需外网/密钥)
    embedding_provider: str = "local"

    # OpenAI Configuration
    openai_api_key: Optional[str] = None
    openai_embedding_model: str = "text-embedding-3-small"

    # Local embedding configuration (sentence-transformers)
    local_embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_device: str = "cpu"
    
    # Chroma Configuration
    chroma_client_mode: str = "http"  # "http" or "local"
    chroma_persist_directory: str = "./lg-aide-chroma-db"
    chroma_collection_prefix: str = "lg_aide"

    # --- New for HTTP Client ---
    chroma_host: str = "localhost"
    chroma_port: int = 8101
    # --- End New ---
    
    # Vector Configuration
    vector_dimension: int = 512  # bge-small-zh-v1.5；openai text-embedding-3-small 为 1536
    # 余弦相似度阈值：bge/text-embedding 的相关匹配多在 0.45~0.65，0.7 会把真实命中全滤掉
    similarity_threshold: float = 0.35
    default_query_limit: int = 10
    
    @classmethod
    def from_env(cls) -> "VectorConfig":
        """Load configuration from environment variables"""
        provider = os.getenv("EMBEDDING_PROVIDER", "local").strip().lower()

        openai_api_key = os.getenv("EMBEDDING_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if provider == "openai" and not openai_api_key:
            raise ValueError("EMBEDDING_PROVIDER=openai 时需要 OPENAI_API_KEY 或 EMBEDDING_OPENAI_API_KEY")

        local_model = os.getenv("LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
        default_dim = "512" if local_model.startswith("BAAI/bge-small") else "384"

        return cls(
            embedding_provider=provider,
            openai_api_key=openai_api_key,
            openai_embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            local_embedding_model=local_model,
            embedding_device=os.getenv("EMBEDDING_DEVICE", "cpu"),

            # Chroma config
            chroma_client_mode=os.getenv("CHROMA_CLIENT_MODE", "http"),
            chroma_persist_directory=os.getenv("CHROMA_PERSIST_DIR", "./lg-aide-chroma-db"),
            chroma_collection_prefix=os.getenv("CHROMA_COLLECTION_PREFIX", "lg_aide"),

            # New HTTP client config
            chroma_host=os.getenv("CHROMA_HOST", "localhost"),
            chroma_port=int(os.getenv("CHROMA_PORT", "8101")),
            
            # Vector Configuration
            vector_dimension=int(os.getenv("VECTOR_DIMENSION", default_dim if provider == "local" else "1536")),
            similarity_threshold=float(os.getenv("SIMILARITY_THRESHOLD", "0.35")),
            default_query_limit=int(os.getenv("DEFAULT_QUERY_LIMIT", "10"))
        )
    
    def get_collection_name(self, user_id: str) -> str:
        """Generate collection name for user isolation"""
        return f"{self.chroma_collection_prefix}_user_{user_id}" 