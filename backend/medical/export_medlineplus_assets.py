"""Export the admitted MedlinePlus pilot as provenance-rich JSONL assets."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

from .chunking import chunk_document
from .data_registry import assert_answer_eligible
from .import_medlineplus import DEFAULT_ARCHIVE, import_archive
from .knowledge_base import INDEX_VERSION, load_corpus


DATASET_ID = "medlineplus_topics"
DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[2] / "medical-rag-data"


def _write_jsonl(path: Path, records: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records).encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def export_assets(data_root: Path = DEFAULT_DATA_ROOT, archive: Path = DEFAULT_ARCHIVE,
                  collected_at: date | None = None) -> dict:
    assert_answer_eligible(DATASET_ID)
    collected_at = collected_at or date.today()
    imported_dir = data_root / "staging" / "medlineplus_imported"
    source_manifest = import_archive(archive, imported_dir, collected_at=collected_at)
    documents = load_corpus(imported_dir)
    normalized: list[dict] = []
    chunks: list[dict] = []
    for document in documents:
        normalized.append({
            **document.model_dump(mode="json"),
            "dataset_id": DATASET_ID,
            "language": "en",
            "jurisdiction": "US",
            "content_type": "health_topic_summary",
            "evidence_type": "patient_education_summary",
            "license_id": DATASET_ID,
            "clinical_reviewed": False,
        })
        for chunk in chunk_document(document.body, document.title):
            indexed_text = f"{document.title}\n{chunk.section_path}\n{chunk.text}"
            chunk_id = hashlib.sha256(
                f"{document.doc_id}:{document.version}:{chunk.section_path}:{chunk.index}:{chunk.text}".encode("utf-8")
            ).hexdigest()[:32]
            chunks.append({
                "chunk_id": chunk_id,
                "dataset_id": DATASET_ID,
                "doc_id": document.doc_id,
                "doc_version": document.version,
                "title": document.title,
                "section_path": chunk.section_path,
                "section_chunk_index": chunk.index,
                "chunker_version": INDEX_VERSION,
                "text": chunk.text,
                "indexed_text": indexed_text,
                "source_url": str(document.source_url),
                "source_locator": document.source_locator,
                "source_sha256": document.source_sha256,
                "source_version": document.source_version,
                "source_created_at": document.source_published_at.isoformat(),
                "source_collected_at": document.source_collected_at.isoformat(),
                "license_id": DATASET_ID,
                "review_status": document.status,
                "clinical_reviewed": False,
            })
    normalized_path = data_root / "normalized" / "medlineplus_topics_2026-09-19.jsonl"
    chunks_path = data_root / "rag" / "medlineplus_topics_2026-09-19.jsonl"
    normalized_sha = _write_jsonl(normalized_path, normalized)
    chunks_sha = _write_jsonl(chunks_path, chunks)
    manifest = {
        "dataset_id": DATASET_ID,
        "source_archive_sha256": source_manifest["archive_sha256"],
        "source_xml_sha256": source_manifest["xml_sha256"],
        "source_version": source_manifest["source_date"],
        "documents": len(normalized),
        "chunks": len(chunks),
        "normalized_sha256": normalized_sha,
        "chunks_sha256": chunks_sha,
        "license_id": DATASET_ID,
        "clinical_reviewed": False,
    }
    manifest_path = data_root / "rag" / "medlineplus_topics_2026-09-19_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Export admitted MedlinePlus data assets")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    args = parser.parse_args()
    print(json.dumps(export_assets(args.data_root, args.archive), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
