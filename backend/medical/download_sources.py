"""Fetch only the four pinned official source files for local reproduction."""

import hashlib
import json
from urllib.request import Request, urlopen

from .source_pipeline import DOWNLOADS, OUTPUT, SOURCES


def main() -> None:
    manifest = json.loads((OUTPUT / "source_manifest.json").read_text(encoding="utf-8"))
    expected = {item["id"]: item for item in manifest["sources"]}
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    for source_id, definition in SOURCES.items():
        item = expected[source_id]
        if item["url"] != definition["url"] or item["file"] != definition["file"]:
            raise ValueError(f"pinned source changed: {source_id}")
        target = DOWNLOADS / definition["file"]
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == item["sha256"]:
            print(f"verified existing source: {source_id}")
            continue
        request = Request(definition["url"], headers={"User-Agent": "Aide-local-source-research/1.0"})
        with urlopen(request, timeout=30) as response:
            content = response.read(10_000_001)
        if len(content) > 10_000_000 or hashlib.sha256(content).hexdigest() != item["sha256"]:
            raise ValueError(f"source content differs from pinned manifest: {source_id}")
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(target)
        print(f"downloaded and verified source: {source_id}")


if __name__ == "__main__":
    main()
