"""Exact, whitespace-tolerant reconstruction of legacy chunk provenance."""
from dataclasses import dataclass
from functools import lru_cache
import hashlib
from pathlib import Path
import re

from .chunking import chunk_document


def body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def chunk_key(document, chunk) -> str:
    value = f"{document.doc_id}:{document.version}:{chunk.section_path}:{chunk.index}:{chunk.text}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class Binding:
    text: str
    body_sha256: str
    version: int
    source_sha256: str | None
    # text_start, text_end, body_start, body_end. Unverified headings are excluded.
    segments: tuple[tuple[int, int, int, int], ...]
    reason: str | None = None
    section_path: str | None = None


class SourceResolver:
    def __init__(self, documents, chunker=None):
        self.documents = {d.doc_id: d for d in documents}
        if len(self.documents) != len(documents):
            raise ValueError("duplicate source documents")
        self.bindings = {}
        for document in documents:
            if chunker is not None:
                for chunk in chunker.chunks(document):
                    alternatives = []
                    for text, segments in ((chunk.text, chunk.segments), (chunk.context, chunk.context_segments)):
                        if any(not (0 <= a < b <= len(text) and 0 <= c < d <= len(document.body))
                               or text[a:b] != document.body[c:d] for a, b, c, d in segments):
                            raise ValueError("native source offsets do not match canonical body")
                        alternatives.append(Binding(text, body_hash(document.body), document.version,
                                                    document.source_sha256, segments, section_path=chunk.section_path))
                    self.bindings[(document.doc_id, chunk.chunk_id)] = alternatives
                continue
            headings = {}
            cursor = 0
            for raw in document.body.splitlines(keepends=True):
                stripped = raw.strip()
                match = re.match(r"^#{1,6}\s+(.+?)\s*$", stripped)
                if match:
                    heading = match.group(1)
                    origin = cursor + len(raw) - len(raw.lstrip()) + match.start(1)
                    headings.setdefault(heading, []).append(origin)
                cursor += len(raw)
            positions = [i for i, char in enumerate(document.body) if not char.isspace()]
            compact = "".join(document.body[i] for i in positions)
            for chunk in chunk_document(document.body, document.title):
                prefix = f"{document.title}\n{chunk.section_path}\n"
                text = prefix + chunk.text
                local = [i for i, char in enumerate(chunk.text) if not char.isspace()]
                needle = "".join(chunk.text[i] for i in local)
                start = compact.find(needle) if needle else -1
                reason = ("not_exactly_located" if start < 0 else
                          "ambiguous_source_range" if compact.find(needle, start + 1) >= 0 else None)
                segments = []
                if reason is None:
                    # Only headings demonstrably copied from this body receive
                    # offsets. A generated document title is never evidence.
                    path_cursor = len(document.title)+1
                    for name in chunk.section_path.split(" / "):
                        origins = headings.get(name, [])
                        if len(origins) == 1:
                            segments.append((path_cursor, path_cursor+len(name), origins[0], origins[0]+len(name)))
                        path_cursor += len(name)+3
                    for offset, text_index in enumerate(local):
                        target, origin = len(prefix) + text_index, positions[start + offset]
                        if segments and segments[-1][1] == target and segments[-1][3] == origin:
                            a, _, c, _ = segments[-1]
                            segments[-1] = (a, target + 1, c, origin + 1)
                        else:
                            segments.append((target, target + 1, origin, origin + 1))
                self.bindings[(document.doc_id, chunk_key(document, chunk))] = Binding(
                    text, body_hash(document.body), document.version, document.source_sha256,
                    tuple(segments), reason, chunk.section_path)

    def resolve(self, hit, visible_text: str) -> dict:
        if not hit.text.startswith(visible_text):
            raise ValueError("evidence must be an exact visible prefix")
        return self.resolve_intervals(hit, [[0, len(visible_text)]])

    def resolve_intervals(self, hit, intervals) -> dict:
        if any(type(a) is not int or type(b) is not int or not 0 <= a <= b <= len(hit.text)
               for a, b in intervals):
            raise ValueError("visible source intervals are out of bounds")
        binding = self.bindings.get((hit.doc_id, hit.chunk_id))
        native = isinstance(binding, list)
        if native:
            binding = next((row for row in binding if row.text == hit.text), binding[0])
        document = self.documents.get(hit.doc_id)
        reason = "unknown_chunk"
        if binding:
            reason = (binding.reason or
                      ("content_mismatch" if hit.text != binding.text else
                       "version_mismatch" if hit.document_version != binding.version else
                       "source_hash_mismatch" if hit.source_sha256 != binding.source_sha256 else
                       "source_metadata_mismatch" if (hit.title != document.title
                           or hit.section_path != binding.section_path
                           or hit.source_url != str(document.source_url)
                           or hit.source_org != document.source_org
                           or hit.usage_scope != document.usage_scope) else None))
        if reason:
            return {"status": "unmapped", "reason": reason, "ranges": []}
        ranges = []
        for start, end, origin, _ in binding.segments:
            for a, b in intervals:
                left, right = max(start, a), min(end, b)
                if right > left:
                    ranges.append([origin+left-start, origin+right-start])
        return {"status": "verified_offsets" if native else "verified_reconstruction", "document_version": binding.version,
                "body_sha256": binding.body_sha256, "ranges": ranges}


def default_resolver():
    directory = Path(__file__).with_name("source_corpus")
    signature = tuple((path.name, path.stat().st_mtime_ns, path.stat().st_size)
                      for path in sorted(directory.glob("*.json")))
    return _resolver_for_snapshot(signature)


@lru_cache(maxsize=2)
def _resolver_for_snapshot(signature):
    from .knowledge_base import load_corpus
    directory = Path(__file__).with_name("source_corpus")
    resolver = SourceResolver(load_corpus(directory))
    after = tuple((path.name, path.stat().st_mtime_ns, path.stat().st_size)
                  for path in sorted(directory.glob("*.json")))
    if after != signature:
        raise RuntimeError("source snapshot changed while loading")
    return resolver
