"""Replay reviewed Chinese HTML selections as exact source import bundles.

Recipes record selection, not clinical approval. Editorial titles and Markdown
formatting cannot become literal answer evidence. No network or model calls.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .audit_source_snapshot import original_asset_path
from .experiment import ROOT, digest
from .schema import MedicalDocument
from .source_origins import verify_origin
from .source_pipeline import paragraphs, sha256
from .source_provenance import body_hash


def build_bundle(spec, raw_root):
    asset = {"root": "raw", "file": spec["html_path"], "sha256": spec["html_sha256"],
             "url": spec["source_url"], "format": "original_http_html"}
    original = original_asset_path(asset, raw_root)
    if sha256(original) != asset["sha256"]:
        raise ValueError("reviewed original HTML differs")
    parts = paragraphs(original.read_bytes().decode("utf-8"))
    source = "\n\n".join(parts)+"\n"
    if type(spec["paragraph_count"]) is not int or spec["paragraph_count"] <= 0 or len(parts) != spec["paragraph_count"]:
        raise ValueError("reviewed paragraph extraction differs")
    capture_path = original_asset_path({"root": "raw", "file": spec["capture_path"]}, raw_root)
    if capture_path.suffix != ".txt" or capture_path.read_bytes() != source.encode("utf-8"):
        raise ValueError("derived capture differs from original HTML extraction")
    if hashlib.sha256(source.encode("utf-8")).hexdigest() != spec["capture_sha256"]:
        raise ValueError("reviewed capture hash differs")
    selected, headings = spec["selected_paragraphs"], spec["heading_paragraphs"]
    if (not isinstance(selected, list) or not selected
            or any(type(n) is not int or not 0 <= n < len(parts) for n in selected)
            or selected != sorted(set(selected))
            or not isinstance(headings, list) or any(type(n) is not int for n in headings)
            or len(headings) != len(set(headings)) or not set(headings).issubset(selected)):
        raise ValueError("selections need unique ordered paragraph indices and selected headings")
    omissions = spec["omitted_paragraphs"]
    if (not isinstance(omissions, dict) or set(omissions) != {str(i) for i in range(len(parts)) if i not in selected}
            or any(not isinstance(reason, str) or not reason.strip() for reason in omissions.values())):
        raise ValueError("all unselected paragraphs need explicit omission reasons")
    offsets, cursor = [], 0
    for part in parts:
        offsets.append(cursor); cursor += len(part)+2
    title = spec["document"]["title"]
    body = "# "+title
    segments = [{"body_range": [0, 2], "kind": "markup", "capture_range": None},
                {"body_range": [2, len(body)], "kind": "editorial_heading", "capture_range": None}]
    for index in selected:
        body += "\n\n"
        if index in headings:
            at = len(body); body += "## "
            segments.append({"body_range": [at, len(body)], "kind": "markup", "capture_range": None})
        at = len(body); body += parts[index]
        segments.append({"body_range": [at, len(body)], "kind": "source_heading" if index in headings else "source_text",
                         "capture_range": [offsets[index], offsets[index]+len(parts[index])], "paragraph_index": index})
    doc = MedicalDocument.model_validate({**spec["document"], "source_url": spec["source_url"],
                                          "source_sha256": asset["sha256"], "body": body})
    origin = {"schema_version": 1, "coordinate_unit": "unicode_codepoints", "doc_id": doc.doc_id,
              "document_version": doc.version, "body_sha256": body_hash(body),
              "source_url": str(doc.source_url), "source_asset_sha256": doc.source_sha256,
              "declared_source_hash_kind": "original_http_html",
              "capture": {"path": spec["capture_path"], "sha256": spec["capture_sha256"],
                          "method": "html_parser_paragraph_text_whitespace_normalized",
                          "format": "derived_text_not_original_html", "source_asset": asset,
                          "source_collected_at": str(doc.source_collected_at),
                          "paragraph_count": len(parts), "implementation_file": "medical/source_pipeline.py",
                          "implementation_sha256": sha256(Path(__file__).with_name("source_pipeline.py"))},
              "segments": segments,
              "omissions": [{"paragraph_index": i, "capture_range": [offsets[i], offsets[i]+len(parts[i])],
                             "reason": omissions[str(i)]} for i in range(len(parts)) if i not in selected],
              "selection_recipe_sha256": digest(spec), "public_answer_eligible": False}
    verify_origin(doc, origin, raw_root)
    return {"document": doc.model_dump(mode="json"), "origin": origin}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    allowed = (ROOT/"medical-rag-data/staging").resolve()
    output = args.output.resolve()
    if not output.is_relative_to(allowed) or output == allowed or output.exists():
        raise ValueError("bundle output must be a new directory within staging")
    recipe = json.loads(args.recipe.read_text(encoding="utf-8"))
    if type(recipe.get("schema_version")) is not int or recipe["schema_version"] != 1:
        raise ValueError("unknown source selection recipe schema")
    bundles = [build_bundle(spec, ROOT/"medical-rag-data/raw") for spec in recipe["sources"]]
    ids = [b["document"]["doc_id"] for b in bundles]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("source batch needs unique document IDs")
    output.mkdir(parents=True)
    for bundle in bundles:
        with (output/f"{bundle['document']['doc_id']}.json").open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(bundle, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"bundles": ids, "serving_index_switched": False}, ensure_ascii=False))
