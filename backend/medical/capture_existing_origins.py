"""Reconstruct literal origins from pinned local PDF/HTML source assets.

Derived text is explicitly a normalized extraction, not the original asset.
The original bytes and extraction implementation are independently hashed.
No download, serving index, or historical corpus modification is performed.
"""
import hashlib
from importlib.metadata import version
import json
from pathlib import Path

from .source_origins import verify_origin
from .source_pipeline import DOWNLOADS, explanation_clauses, notice_clauses, paragraphs, sha256
from .source_provenance import body_hash


BASE = Path(__file__).resolve().parent


def _save_capture(raw_root, relative, text):
    root = Path(raw_root).resolve()
    path = (root/relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("derived capture must stay inside the raw root")
    data = text.encode("utf-8")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("never replace a differing source capture")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
    return {"path": relative.as_posix(), "sha256": hashlib.sha256(data).hexdigest()}


def _manifest(doc, capture, segments):
    return {"schema_version": 1, "coordinate_unit": "unicode_codepoints", "doc_id": doc.doc_id,
            "document_version": doc.version, "body_sha256": body_hash(doc.body),
            "source_url": str(doc.source_url), "source_asset_sha256": doc.source_sha256,
            "capture": capture, "segments": segments, "public_answer_eligible": False}


def map_editorial_document(doc, payload, capture_text, capture, *, paragraph_selection=False):
    """A generated H1 plus exact, ordered source selections are permitted."""
    heading, separator, body = doc.body.partition("\n")
    if not separator or not heading.startswith("# ") or body != payload:
        raise ValueError(f"canonical payload differs from source extraction: {doc.doc_id}")
    offset = len(heading)+1
    parts = [{"body_range": [0, 2], "kind": "markup", "capture_range": None},
             {"body_range": [2, len(heading)], "kind": "editorial_heading", "capture_range": None}]
    units = payload.split("\n\n") if paragraph_selection else [payload]
    previous_end = 0
    for unit in units:
        start = capture_text.find(unit)
        if not unit or start < previous_end or capture_text.find(unit, start+1) >= 0:
            raise ValueError(f"source payload must have one exact ordered location: {doc.doc_id}")
        parts.append({"body_range": [offset, offset+len(unit)], "kind": "source_text",
                      "capture_range": [start, start+len(unit)]})
        offset += len(unit)+2
        previous_end = start+len(unit)
    return _manifest(doc, capture, parts)


def reconstruct(documents, raw_root, downloads=DOWNLOADS, source_manifest=BASE/"source_corpus/source_manifest.json"):
    """Verify and map 66 PDF clauses plus the two original HTML excerpts."""
    docs = {d.doc_id: d for d in documents}
    assets = {entry["id"]: entry for entry in json.loads(source_manifest.read_text(encoding="utf-8"))["sources"]}
    paths = {}
    for key in ("notice", "explanation", "chest", "abdomen"):
        entry = assets[key]
        path = (downloads/entry["file"]).resolve()
        if not path.is_relative_to(downloads.resolve()) or sha256(path) != entry["sha256"]:
            raise ValueError(f"pinned source asset changed: {key}")
        paths[key] = path
    extraction = {"implementation_file": "medical/source_pipeline.py",
                  "implementation_sha256": sha256(BASE/"source_pipeline.py")}
    clauses = explanation_clauses(paths["explanation"], notice_clauses(paths["notice"]))
    full_text = "\n\n".join(row[0] for row in clauses)+"\n"
    capture = {**_save_capture(raw_root, Path("nhc-health-literacy-2024/2026-10-17/extracted-clauses.txt"), full_text),
               "method": "pdf_extraction_with_linewrap_and_page_number_normalization",
               "format": "derived_text_not_original_pdf", "source_asset": assets["explanation"],
               "cross_check_asset": assets["notice"], "pypdf_version": version("pypdf"), **extraction}
    origins = {}
    for number, (payload, first, last) in enumerate(clauses, 1):
        doc = docs[f"NHC-HL2024-{number:02d}"]
        if doc.source_sha256 != assets["explanation"]["sha256"] or str(doc.source_url) != assets["explanation"]["url"]:
            raise ValueError("canonical PDF asset binding differs")
        origin = map_editorial_document(doc, payload, full_text, {**capture, "pdf_pages": [first, last]})
        verify_origin(doc, origin, raw_root)
        origins[doc.doc_id] = origin
    for key, doc_id in (("chest", "BJ-EMERG-CHEST-2022"), ("abdomen", "GZ-POSTMEAL-ABDOMEN-2026")):
        doc = docs[doc_id]
        if doc.source_sha256 != assets[key]["sha256"] or str(doc.source_url) != assets[key]["url"]:
            raise ValueError("canonical HTML asset binding differs")
        text = "\n\n".join(paragraphs(paths[key].read_text(encoding="utf-8")))+"\n"
        local_capture = {**_save_capture(raw_root, Path(f"{key}-official-html/2026-10-17/extracted-paragraphs.txt"), text),
                         "method": "html_parser_paragraph_text_whitespace_normalized",
                         "format": "derived_text_not_original_html", "source_asset": assets[key], **extraction}
        origin = map_editorial_document(doc, doc.body.partition("\n")[2], text, local_capture,
                                        paragraph_selection=(key == "chest"))
        verify_origin(doc, origin, raw_root)
        origins[doc.doc_id] = origin
    return origins


def narrow_abdominal_excerpt(document, origin, raw_root):
    """Version the new snapshot only; the old paragraph included section III."""
    from datetime import date
    from .schema import MedicalDocument
    marker = " 三、高危人群要早识别、少硬扛 "
    if document.doc_id != "GZ-POSTMEAL-ABDOMEN-2026" or document.version != 1 or document.body.count(marker) != 1:
        raise ValueError("unexpected abdominal snapshot; review a new normalization version")
    body, omitted = document.body.split(marker)
    if not body.endswith("以免掩盖病情、延误诊治。") or not omitted:
        raise ValueError("abdominal warning boundary differs")
    updated = document.model_dump(mode="json")
    updated.update(version=2, body=body, reviewed_at="2026-10-17",
                   reviewer="Aide literal-source and section-boundary check (non-clinician)",
                   source_locator="第二节危险信号，从‘如果疼痛在短时间内持续加重’至‘以免掩盖病情、延误诊治。’；不含第三节高危人群")
    result = MedicalDocument.model_validate(updated)
    if result.next_review_at < date(2026, 10, 17):
        raise ValueError("corrected source requires a current review date")
    capture_text = (Path(raw_root)/origin["capture"]["path"]).read_bytes().decode("utf-8")
    mapped = map_editorial_document(result, result.body.partition("\n")[2], capture_text, origin["capture"])
    mapped["previous_snapshot"] = {"version": document.version, "body_sha256": body_hash(document.body),
                                   "reason": "exclude_unintentionally_carried_section_III"}
    old_start = origin["segments"][-1]["capture_range"][0]
    cut = len(body.partition("\n")[2])
    mapped["omissions"] = [{"capture_range": [old_start+cut, origin["segments"][-1]["capture_range"][1]],
                            "reason": "following_section_outside_declared_excerpt"}]
    verify_origin(result, mapped, raw_root)
    return result, mapped
