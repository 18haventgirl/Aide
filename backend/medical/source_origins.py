"""Verify canonical body parts against a saved source capture.

This proves copied text in the declared capture format. A rendered-text
capture is explicitly NOT an original HTTP/HTML response or clinical review.
Editorial/metadata/markup parts can never become literal source evidence.
"""
import hashlib
from pathlib import Path

from .source_provenance import SourceResolver, body_hash


SOURCE_KINDS = {"source_text", "source_heading"}
NON_SOURCE_KINDS = {"editorial_heading", "metadata", "markup"}


def _span(value, length):
    if (not isinstance(value, list) or len(value) != 2 or any(type(n) is not int for n in value)
            or not 0 <= value[0] < value[1] <= length):
        raise ValueError("invalid origin coordinate range")
    return value


def verify_origin(document, manifest, raw_root):
    if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
            or manifest.get("coordinate_unit") != "unicode_codepoints"
            or manifest.get("doc_id") != document.doc_id or type(manifest.get("document_version")) is not int
            or manifest["document_version"] != document.version or manifest.get("body_sha256") != body_hash(document.body)
            or manifest.get("source_asset_sha256") != document.source_sha256
            or manifest.get("source_url") != str(document.source_url)):
        raise ValueError("origin document snapshot differs")
    root = Path(raw_root).resolve()
    relative = Path(manifest["capture"]["path"])
    path = (root/relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root) or path.suffix != ".txt":
        raise ValueError("capture must be a text file within the approved raw root")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["capture"]["sha256"]:
        raise ValueError("source capture hash differs")
    text = raw.decode("utf-8")
    segments, seen, coverage = [], set(), set()
    for part in manifest["segments"]:
        a, b = _span(part.get("body_range"), len(document.body))
        kind = part.get("kind")
        if kind not in SOURCE_KINDS | NON_SOURCE_KINDS:
            raise ValueError("unknown origin kind")
        positions = set(range(a, b))
        if seen & positions:
            raise ValueError("overlapping origin claims")
        seen |= positions
        coverage |= positions
        if kind in SOURCE_KINDS:
            x, y = _span(part.get("capture_range"), len(text))
            if document.body[a:b] != text[x:y]:
                raise ValueError("claimed literal source does not match capture")
        elif part.get("capture_range") is not None:
            raise ValueError("editorial/metadata/markup cannot claim source offsets")
        segments.append(part)
    required = {i for i, char in enumerate(document.body) if not char.isspace()}
    if not required.issubset(coverage):
        raise ValueError("unclassified canonical body characters")
    return {"segments": segments, "capture_sha256": manifest["capture"]["sha256"],
            "capture_method": manifest["capture"]["method"], "capture_text": text}


def intersect(ranges, allowed):
    return [[max(a, x), min(b, y)] for a, b in ranges for x, y in allowed if max(a, x) < min(b, y)]


def validate_literal_references(cases, resolver):
    from .evaluation.metrics import validate_references
    validate_references(cases, list(resolver.documents.values()))
    for case in cases:
        for ref in case.get("expected_evidence", []):
            origin = resolver.origins.get(ref["doc_id"])
            if origin is None: raise ValueError("gold source origin is missing")
            literal = {i for part in origin["segments"] if part["kind"] in SOURCE_KINDS
                       for i in range(*part["body_range"])}
            body = resolver.documents[ref["doc_id"]].body
            for field in ("ranges", "required_conditions"):
                for start, end in ref.get(field, []):
                    required = {i for i in range(start, end) if not body[i].isspace()}
                    if not required.issubset(literal):
                        raise ValueError("gold contains editorial/metadata/unverified source text")


class OriginResolver:
    """Optional strict resolver for versioned NEW corpus/evaluation snapshots."""
    def __init__(self, documents, manifests, raw_root, chunker=None):
        self.base = SourceResolver(documents, chunker)
        self.documents = self.base.documents
        self.origins = {}
        for doc_id, manifest in manifests.items():
            if doc_id not in self.documents:
                raise ValueError("origin references an unknown document")
            self.origins[doc_id] = verify_origin(self.documents[doc_id], manifest, raw_root)

    def resolve(self, hit, visible_text):
        if not hit.text.startswith(visible_text): raise ValueError("evidence must be an exact visible prefix")
        return self.resolve_intervals(hit, [[0, len(visible_text)]])

    def resolve_intervals(self, hit, intervals):
        mapping = self.base.resolve_intervals(hit, intervals)
        if mapping["status"] == "unmapped": return mapping
        origin = self.origins.get(hit.doc_id)
        if origin is None:
            return {"status": "unmapped", "reason": "missing_source_origin_manifest", "ranges": [],
                    "canonical_ranges": mapping["ranges"]}
        literal = [part["body_range"] for part in origin["segments"] if part["kind"] in SOURCE_KINDS]
        editorial = [part["body_range"] for part in origin["segments"] if part["kind"] not in SOURCE_KINDS]
        return {**mapping, "status": "verified_source_capture", "origin_contract": "source_origin_v1",
                "canonical_ranges": mapping["ranges"], "ranges": intersect(mapping["ranges"], literal),
                "non_source_ranges": intersect(mapping["ranges"], editorial),
                "capture_sha256": origin["capture_sha256"], "capture_method": origin["capture_method"]}
