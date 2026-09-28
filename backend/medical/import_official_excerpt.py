"""Import pinned, browser-verified Chinese excerpts for local research.

Hashes identify the saved UTF-8 excerpt, not an HTTP response or the whole page.
The manifest preserves provenance and scope. This is not clinical review.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .schema import MedicalDocument


def build_documents(manifest: dict) -> list[MedicalDocument]:
    documents = []
    seen = set()
    for item in manifest["documents"]:
        body = item["body"]
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if digest != item["excerpt_sha256"]:
            raise ValueError(f"excerpt hash mismatch: {item['doc_id']}")
        if item["doc_id"] in seen:
            raise ValueError("duplicate document id")
        seen.add(item["doc_id"])
        data = {k: v for k, v in item.items() if k != "excerpt_sha256"}
        data.update(
            version=1, language="zh", status="source_checked",
            audience="中文成年人；仅本机研究",
            reviewer="Aide browser source comparison (non-clinician)",
            reviewed_at=manifest["collected_at"],
            source_collected_at=manifest["collected_at"],
            next_review_at=manifest["next_review_at"],
            source_sha256=digest,
            source_version="Browser-verified UTF-8 excerpt snapshot; hash is of excerpt, not full HTML",
            license_note="官方网页公开可读不等于开放许可；仅本机研究，禁止据此宣称可全文再分发。",
        )
        documents.append(MedicalDocument(**data))
    return documents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    documents = build_documents(json.loads(args.manifest.read_text(encoding="utf-8")))
    # Validate the complete batch before writing anything; never remove other sources.
    args.output.mkdir(parents=True, exist_ok=True)
    for document in documents:
        path = args.output / f"{document.doc_id}.json"
        content = document.model_dump_json(indent=2) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") != content:
            raise ValueError(f"refusing to overwrite changed source: {path}")
    for document in documents:
        (args.output / f"{document.doc_id}.json").write_text(
            document.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"documents": len(documents), "output": str(args.output)}))


if __name__ == "__main__":
    main()
