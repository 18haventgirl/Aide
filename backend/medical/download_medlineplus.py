"""Download the pinned MedlinePlus XML archive and verify it before use."""

from __future__ import annotations

import argparse
from pathlib import Path

import requests

from .import_medlineplus import ARCHIVE_SHA256, DEFAULT_ARCHIVE, SOURCE_DOWNLOAD_URL, sha256_bytes


def download(output: Path = DEFAULT_ARCHIVE) -> Path:
    if output.exists() and sha256_bytes(output.read_bytes()) == ARCHIVE_SHA256:
        print(f"verified existing MedlinePlus archive: {output}")
        return output

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    try:
        with requests.get(
            SOURCE_DOWNLOAD_URL,
            headers={"User-Agent": "Aide-local-source-research/1.0"},
            timeout=(15, 120),
            stream=True,
        ) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for block in response.iter_content(chunk_size=1024 * 256):
                    if block:
                        handle.write(block)
        actual = sha256_bytes(temporary.read_bytes())
        if actual != ARCHIVE_SHA256:
            raise ValueError(f"MedlinePlus archive hash changed: {actual}")
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(f"downloaded and verified MedlinePlus archive: {output}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Download pinned MedlinePlus XML")
    parser.add_argument("--output", type=Path, default=DEFAULT_ARCHIVE)
    args = parser.parse_args()
    download(args.output)


if __name__ == "__main__":
    main()
