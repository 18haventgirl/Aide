"""Offline BGE-small-zh-v1.5 inference for the medical source index.

The model is downloaded separately from its official repository. Queries use
the retrieval instruction; source passages do not. This follows BAAI's
Transformers example (CLS pooling followed by L2 normalization).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


MODEL_ID = "BAAI/bge-small-zh-v1.5"
MODEL_REVISION = "7999e1d3359715c523056ef9478215996d62a620"
EXPECTED_WEIGHT_SHA256 = "354763b9b1357bc9c44f62c6be2276321081ed2567773608c0d0785b61d5a026"
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
DIMENSIONS = 512
DEFAULT_MODEL_DIR = Path(__file__).resolve().parent / "models" / "bge-small-zh-v1.5"
REQUIRED_FILES = ("config.json", "model.safetensors", "tokenizer_config.json", "vocab.txt")


def model_file_hash(model_dir: Path) -> str:
    """Content digest used to identify the actual local weight file."""
    weight = model_dir / "model.safetensors"
    digest = hashlib.sha256()
    with weight.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class BGEEmbedding:
    dimensions = DIMENSIONS

    def __init__(self, model_dir: Path | str | None = None, batch_size: int = 8):
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.model_dir = Path(model_dir or os.getenv("MEDICAL_BGE_MODEL_DIR", DEFAULT_MODEL_DIR)).resolve()
        missing = [name for name in REQUIRED_FILES if not (self.model_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(
                f"BGE model is not installed at {self.model_dir}; missing: {', '.join(missing)}"
            )
        self.weight_sha256 = model_file_hash(self.model_dir)
        if self.weight_sha256 != EXPECTED_WEIGHT_SHA256:
            raise ValueError("local BGE weights differ from the pinned official model")
        self.batch_size = batch_size
        self._tokenizer = None
        self._model = None
        self._torch = None

    def name(self) -> str:
        return f"{MODEL_ID}@{MODEL_REVISION}"

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as error:
            raise RuntimeError("BGE inference requires torch and transformers") from error

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_dir, local_files_only=True)
        self._model = AutoModel.from_pretrained(
            self.model_dir, local_files_only=True, use_safetensors=True
        ).to("cpu")
        self._model.eval()
        if self._model.config.hidden_size != DIMENSIONS:
            raise ValueError(f"unexpected BGE dimension: {self._model.config.hidden_size}")
        self._torch = torch

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._load()
        output: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            tokens = self._tokenizer(
                batch, padding=True, truncation=True, max_length=512, return_tensors="pt"
            )
            with self._torch.inference_mode():
                hidden = self._model(**tokens).last_hidden_state[:, 0]
                vectors = self._torch.nn.functional.normalize(hidden, p=2, dim=1)
            output.extend(vectors.cpu().tolist())
        return output

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(list(texts))

    def embed_queries(self, queries: list[str]) -> list[list[float]]:
        return self._encode([QUERY_INSTRUCTION + query for query in queries])

    def __call__(self, input: list[str]) -> list[list[float]]:
        # Chroma may call this for documents. MedicalKnowledgeBase explicitly
        # calls embed_queries when searching, so the instruction is not lost.
        return self.embed_documents(list(input))
