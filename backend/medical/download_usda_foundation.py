"""Download and verify the pinned official USDA Foundation Foods archive."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import requests
from .data_registry import assert_answer_eligible

from .import_usda_foundation import ARCHIVE, ARCHIVE_SHA256, ARCHIVE_URL


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(output: Path = ARCHIVE) -> Path:
    assert_answer_eligible("usda_fdc")
    if output.exists() and _sha256_file(output) == ARCHIVE_SHA256:
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    try:
        with requests.get(
            ARCHIVE_URL,
            headers={"User-Agent": "Aide-local-source-research/1.0"},
            timeout=(15, 120),
            stream=True,
        ) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for block in response.iter_content(chunk_size=256 * 1024):
                    if block:
                        handle.write(block)
        actual = _sha256_file(temporary)
        if actual != ARCHIVE_SHA256:
            raise ValueError(f"USDA archive SHA256 mismatch: {actual}")
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Download pinned USDA Foundation Foods archive")
    parser.add_argument("--output", type=Path, default=ARCHIVE)
    args = parser.parse_args()
    print(download(args))


if __name__ == "__main__":
    main()
