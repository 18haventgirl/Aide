"""Replay verified Chinese symptom excerpts from pinned primary and parallel transcripts."""
import argparse
import hashlib
import json
from pathlib import Path

from .audit_source_snapshot import original_asset_path
from .capture_existing_origins import _save_capture
from .experiment import ROOT, digest
from .knowledge_base import load_corpus
from .schema import MedicalDocument
from .source_origins import verify_origin
from .source_pipeline import paragraphs, sha256
from .source_provenance import body_hash


RAW = ROOT / "medical-rag-data/raw"
STAGING = ROOT / "medical-rag-data/staging"
RECIPE = ROOT / "medical-rag-data/registry/legacy_symptom_origins_20261102.json"


def render_excerpt(previous, sections, rows):
    """Headings are inherited editorial labels. Only the selected source slices are copied."""
    headings = [line for line in previous.body.splitlines() if line.startswith("# ")]
    if not sections or len(headings) != len(sections):
        raise ValueError("each original section must have a source selection")
    offsets = []
    cursor = 0
    for row in rows:
        offsets.append(cursor)
        cursor += len(row) + 2
    body = ""
    segments = []
    last_end = 0
    for heading, selections in zip(headings, sections):
        if not selections:
            raise ValueError("empty source selection")
        if body:
            body += "\n"
        at = len(body)
        body += heading
        segments.extend([
            {"body_range": [at, at + 2], "kind": "markup", "capture_range": None},
            {"body_range": [at + 2, len(body)], "kind": "editorial_heading", "capture_range": None},
        ])
        body += "\n"
        for selection in selections:
            if len(selection) != 3 or any(type(value) is not int for value in selection):
                raise ValueError("invalid paragraph slice")
            index, start, end = selection
            if not 0 <= index < len(rows) or not 0 <= start < end <= len(rows[index]):
                raise ValueError("source selection out of bounds")
            source_start = offsets[index] + start
            if source_start < last_end:
                raise ValueError("source selections overlap or are out of order")
            last_end = offsets[index] + end
            at = len(body)
            body += rows[index][start:end]
            segments.append({"body_range": [at, len(body)], "kind": "source_text",
                             "paragraph_index": index, "capture_range": [source_start, last_end]})
    return body, segments


def build_record(previous, spec, collected_at, raw_root):
    if (spec["doc_id"] != previous.doc_id or digest(previous.model_dump(mode="json")) != spec["previous_document_sha256"]
            or previous.source_sha256 != body_hash(previous.body)):
        raise ValueError("previous document differs from the reviewed legacy excerpt")
    asset = {"root": "raw", "file": spec["html_path"], "sha256": spec["html_sha256"],
             "url": spec["source_url"], "format": "original_http_html"}
    original = original_asset_path(asset, raw_root)
    original_bytes = original.read_bytes()
    if hashlib.sha256(original_bytes).hexdigest() != asset["sha256"]:
        raise ValueError("pinned HTML asset differs")
    rows = paragraphs(original_bytes.decode("utf-8"))
    extracted = "\n\n".join(rows) + "\n"
    if len(rows) != spec["paragraph_count"] or body_hash(extracted) != spec["capture_sha256"]:
        raise ValueError("pinned derived paragraph extraction differs")
    body, segments = render_excerpt(previous, spec["sections"], rows)
    if body_hash(body) != spec["body_sha256"]:
        raise ValueError("selected body differs from reviewed version")
    if spec["kind"] == "same_original_page":
        if (body != previous.body or str(previous.source_url) != spec["source_url"]
                or str(previous.source_published_at) != spec["source_published_at"]):
            raise ValueError("origin-only update must preserve original document and source")
        doc = previous
        hash_kind = "utf8_canonical_excerpt_not_original_html"
    elif spec["kind"] == "official_parallel_transcript":
        if str(previous.source_url) == spec["source_url"]:
            raise ValueError("parallel transcript must identify its own publication URL")
        doc = MedicalDocument.model_validate({
            **previous.model_dump(mode="json"), "version": previous.version + 1, "body": body,
            "source_url": spec["source_url"], "source_org": spec["source_org"], "source_sha256": asset["sha256"],
            "source_locator": spec["source_locator"], "source_collected_at": collected_at,
            "source_published_at": spec["source_published_at"], "reviewed_at": collected_at,
            "reviewer": "Aide published transcript and exact source slice verification (non-clinician)",
            "source_version": f"{spec['source_published_at']} official parallel transcript; {collected_at} original HTML capture",
        })
        hash_kind = "original_http_html"
    else:
        raise ValueError("unsupported source relationship")
    relative = Path(asset["file"]).with_name("extracted-paragraphs.txt")
    capture = {**_save_capture(raw_root, relative, extracted), "source_asset": asset,
               "method": "html_parser_paragraph_text_whitespace_normalized", "format": "derived_text_not_original_html",
               "source_collected_at": collected_at, "paragraph_count": len(rows),
               "implementation_file": "medical/source_pipeline.py",
               "implementation_sha256": sha256(Path(__file__).with_name("source_pipeline.py"))}
    origin = {"schema_version": 1, "coordinate_unit": "unicode_codepoints", "doc_id": doc.doc_id,
              "document_version": doc.version, "body_sha256": body_hash(body), "source_url": str(doc.source_url),
              "source_asset_sha256": doc.source_sha256, "declared_source_hash_kind": hash_kind, "capture": capture,
              "segments": segments, "selection_recipe_sha256": digest(spec), "public_answer_eligible": False}
    if doc.version != previous.version:
        origin["previous_snapshot"] = {"version": previous.version, "source_url": str(previous.source_url),
                                       "declared_excerpt_sha256": previous.source_sha256,
                                       "document_sha256": spec["previous_document_sha256"], "reason": spec["reason"]}
    verify_origin(doc, origin, raw_root)
    if doc.version == previous.version:
        return "origin", origin
    return "bundle", {"document": doc.model_dump(mode="json"), "origin": origin}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output == STAGING.resolve() or not output.is_relative_to(STAGING.resolve()):
        raise ValueError("output must be a subdirectory of local staging")
    docs = {doc.doc_id: doc for doc in load_corpus(args.corpus)}
    recipe = json.loads(RECIPE.read_bytes())
    records = {}
    for spec in recipe["sources"]:
        doc_id = spec["doc_id"]
        kind, record = build_record(docs[doc_id], spec, recipe["collected_at"], RAW)
        records[f"{doc_id}.{kind}.json"] = record
    for name, record in records.items():
        _save_capture(output, Path(name), json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"files": sorted(records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
