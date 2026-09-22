"""Download and verify the pinned official BGE reranker for local inference."""

from .bge_reranker import (
    DEFAULT_MODEL_DIR, EXPECTED_WEIGHT_SHA256, MODEL_ID, MODEL_REVISION,
    model_file_hash,
)


def main() -> None:
    from huggingface_hub import snapshot_download

    path = snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=DEFAULT_MODEL_DIR,
        allow_patterns=[
            "config.json", "model.safetensors", "tokenizer.json",
            "tokenizer_config.json", "special_tokens_map.json",
            "sentencepiece.bpe.model",
        ],
    )
    digest = model_file_hash(DEFAULT_MODEL_DIR)
    if digest != EXPECTED_WEIGHT_SHA256:
        raise ValueError("downloaded BGE reranker weights failed the pinned SHA-256 check")
    print(f"Verified {MODEL_ID}@{MODEL_REVISION} at {path}")
    print(f"model.safetensors SHA-256: {digest}")


if __name__ == "__main__":
    main()
