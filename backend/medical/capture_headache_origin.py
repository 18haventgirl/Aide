"""Recover an unchanged headache excerpt's origins from its pinned HTML.

The legacy document hash identifies the UTF-8 excerpt, not the original HTML.
Both bindings are retained explicitly. The archived HTML is copied byte for
byte, and a separate normalized paragraph capture supplies literal offsets.
"""
import hashlib
from pathlib import Path

from .capture_existing_origins import _save_capture
from .source_origins import verify_origin
from .source_pipeline import paragraphs, sha256
from .source_provenance import body_hash


ROOT = Path(__file__).resolve().parents[2]
DOC_ID = "FJ-HEADACHE-20260626"
SOURCE_URL = "https://wjw.fj.gov.cn/ztzl/jkjy/jksh/202606/t20260626_7168302.htm"
ORIGINAL_PATH = ROOT/"medical-rag-data/datasets/chinese-official/2026-09-28/raw/fj-headache.html"
ORIGINAL_SHA = "a75a2d8d43d938b17aad54d605fb98431a7b4b18b010127229bed799279f87e6"
EXCERPT_SHA = "fb81f5ec714a111b181d1a611f90bcbd4257cf45b501742f6b2c188b0f453aa6"
RAW_ASSET = Path("fj-headache-20260626/2026-09-28/original.html")
CAPTURE_PATH = Path("fj-headache-20260626/2026-10-27/extracted-paragraphs.txt")


def save_original(raw_root, relative, raw):
    """Immutable, jailed copy; never replace a differing original asset."""
    root, relative = Path(raw_root).resolve(), Path(relative)
    target = (root/relative).resolve()
    if relative.is_absolute() or not target.is_relative_to(root):
        raise ValueError("original asset must stay inside the raw root")
    if target.exists():
        if target.read_bytes() != raw:
            raise ValueError("never replace a differing original source asset")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)


def map_document_lines(document, source_paragraphs, capture):
    """Map unique ordered lines; only exact whole paragraphs qualify as headings."""
    source = "\n\n".join(source_paragraphs)+"\n"
    source_headings = set(source_paragraphs)
    parts, offset, previous_end = [], 0, 0
    for line in document.body.splitlines(keepends=True):
        unit = line.rstrip("\r\n")
        start = offset
        if unit.startswith("# "):
            parts.append({"body_range": [start, start+2], "kind": "markup", "capture_range": None})
            unit, start = unit[2:], start+2
            kind = "source_heading" if unit in source_headings else "editorial_heading"
        else:
            kind = "source_text"
        if unit:
            part = {"body_range": [start, start+len(unit)], "kind": kind, "capture_range": None}
            if kind.startswith("source_"):
                at = source.find(unit)
                if at < previous_end or source.find(unit, at+1) >= 0:
                    raise ValueError("canonical lines require unique ordered source locations")
                part["capture_range"] = [at, at+len(unit)]
                previous_end = at+len(unit)
            parts.append(part)
        offset += len(line)
    return {"schema_version": 1, "coordinate_unit": "unicode_codepoints", "doc_id": document.doc_id,
            "document_version": document.version, "body_sha256": body_hash(document.body),
            "source_url": str(document.source_url), "source_asset_sha256": document.source_sha256,
            "declared_source_hash_kind": "utf8_canonical_excerpt_not_original_html",
            "capture": capture, "segments": parts, "public_answer_eligible": False}


def build_origin(document, raw_root, original_path=ORIGINAL_PATH):
    """Return an origin sidecar without editing the document or any snapshot."""
    if (document.doc_id != DOC_ID or document.version != 1 or str(document.source_url) != SOURCE_URL
            or document.source_sha256 != EXCERPT_SHA
            or hashlib.sha256(document.body.encode("utf-8")).hexdigest() != EXCERPT_SHA):
        raise ValueError("headache excerpt differs; review a new version")
    original = Path(original_path).read_bytes()
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA:
        raise ValueError("pinned headache HTML differs")
    extracted = paragraphs(original.decode("utf-8"))
    if len(extracted) != 73:
        raise ValueError("headache HTML extraction structure differs")
    source = "\n\n".join(extracted)+"\n"
    capture = {"path": CAPTURE_PATH.as_posix(), "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
               "method": "html_parser_paragraph_text_whitespace_normalized",
               "format": "derived_text_not_original_html", "source_collected_at": "2026-09-28",
               "extracted_at": "2026-10-27", "paragraph_count": len(extracted),
               "source_asset": {"root": "raw", "file": RAW_ASSET.as_posix(), "sha256": ORIGINAL_SHA,
                                "url": SOURCE_URL, "format": "original_html"},
               "implementation_file": "medical/source_pipeline.py",
               "implementation_sha256": sha256(Path(__file__).with_name("source_pipeline.py"))}
    origin = map_document_lines(document, extracted, capture)
    # Check all expected parts before creating even immutable capture files.
    if len([p for p in origin["segments"] if p["kind"] == "source_text"]) != 20:
        raise ValueError("headache excerpt body-line count differs")
    if len([p for p in origin["segments"] if p["kind"] == "source_heading"]) != 2:
        raise ValueError("headache source heading count differs")
    save_original(raw_root, RAW_ASSET, original)
    _save_capture(raw_root, CAPTURE_PATH, source)
    verify_origin(document, origin, raw_root)
    return origin
