"""Offline BGE cross-encoder reranking for medical retrieval.

The model is installed separately from its official repository.  Keeping the
download step explicit lets the service start with a deterministic hybrid
fallback when the optional reranker is not installed.
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
from pathlib import Path


MODEL_ID = "BAAI/bge-reranker-base"
MODEL_REVISION = "af37ed791788201a1cdcf513e0f584f3aa3be105"
EXPECTED_WEIGHT_SHA256 = "ced967c45fd1902eb92716c9ceeca7c95a936770ea9db611f5a841b926e33fbd"
DEFAULT_MODEL_DIR = Path(__file__).resolve().parent / "models" / "bge-reranker-base"
REQUIRED_FILES = (
    "config.json", "model.safetensors", "tokenizer_config.json",
    "sentencepiece.bpe.model",
)


def model_file_hash(model_dir: Path) -> str:
    weight = model_dir / "model.safetensors"
    digest = hashlib.sha256()
    with weight.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class BGEReranker:
    """Lazy CPU cross encoder returning sigmoid-normalized relevance scores."""

    def __init__(self, model_dir: Path | str | None = None, batch_size: int = 4,
                 max_length: int = 384):
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if max_length < 64:
            raise ValueError("max_length must be at least 64")
        self.model_dir = Path(
            model_dir or os.getenv("MEDICAL_RERANKER_MODEL_DIR", DEFAULT_MODEL_DIR)
        ).resolve()
        missing = [name for name in REQUIRED_FILES if not (self.model_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(
                f"BGE reranker is not installed at {self.model_dir}; missing: {', '.join(missing)}"
            )
        self.weight_sha256 = model_file_hash(self.model_dir)
        if self.weight_sha256 != EXPECTED_WEIGHT_SHA256:
            raise ValueError("local BGE reranker weights differ from the pinned official model")
        self.batch_size = batch_size
        self.max_length = max_length
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    def name(self) -> str:
        return f"{MODEL_ID}@{MODEL_REVISION}"

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            try:
                import torch
                from transformers import AutoModelForSequenceClassification, AutoTokenizer
            except ImportError as error:
                raise RuntimeError("BGE reranking requires torch and transformers") from error
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_dir, local_files_only=True)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.model_dir, local_files_only=True, use_safetensors=True
            ).to("cpu")
            self._model.eval()
            self._torch = torch

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        self._load()
        scores: list[float] = []
        pairs = [[query, passage] for passage in passages]
        # A single shared CPU model is cheaper and more predictable than
        # allowing concurrent forwards to oversubscribe all worker threads.
        with self._inference_lock:
            for start in range(0, len(pairs), self.batch_size):
                batch = pairs[start : start + self.batch_size]
                tokens = self._tokenizer(
                    batch, padding=True, truncation=True, max_length=self.max_length,
                    return_tensors="pt",
                )
                with self._torch.inference_mode():
                    logits = self._model(**tokens, return_dict=True).logits.view(-1)
                scores.extend(1.0 / (1.0 + math.exp(-float(value))) for value in logits.cpu())
        return scores
