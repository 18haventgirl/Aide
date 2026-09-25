"""进程内本地 embedding（sentence-transformers）

DeepSeek 等对话网关通常不提供 embeddings 接口，而笔记语义检索必须有向量化能力。
这里用一个本地中文模型补齐这一环：不依赖外网、不需要额外密钥。
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


class LocalSentenceTransformerEmbeddingFunction:
    """适配 chromadb 的 EmbeddingFunction 协议

    模型只在构造时加载一次；sentence-transformers 的导入放在方法内，
    这样选择 openai provider 的部署不需要装 torch 也不会因为缺依赖而报错。
    """

    def __init__(self, model_name: str, device: str = "cpu", normalize: bool = True):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.normalize = normalize
        logger.info(f"Loading local embedding model: {model_name} (device={device})")
        self._model = SentenceTransformer(model_name, device=device)
        # 新版 sentence-transformers 把方法改名为 get_embedding_dimension
        dimension = getattr(self._model, "get_embedding_dimension", None)
        logger.info(
            f"Local embedding model loaded, dimension={dimension() if dimension else self._model.get_sentence_embedding_dimension()}"
        )

    def name(self) -> str:
        return f"local:{self.model_name}"

    def __call__(self, input: List[str]) -> List[List[float]]:
        # BGE 系列检索时推荐给 query 加指令前缀，但 chroma 的 EF 无法区分写入与查询，
        # 归一化后的向量不加前缀也够用，这里保持简单。
        vectors = self._model.encode(list(input), normalize_embeddings=self.normalize)
        return [v.tolist() for v in vectors]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self(texts)

    def embed_query(self, text: str) -> List[float]:
        return self([text])[0]
