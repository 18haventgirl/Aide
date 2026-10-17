"""Experimental, offset-preserving parent/child chunks for Chinese sources.

No synthetic medical content is added. A child is ranked; bounded surrounding
source sentences are expanded only after ranking. Oversized atomic units are
explicitly marked rather than silently claiming their conditions are intact.
"""
from dataclasses import dataclass
import hashlib
import json
import re

from .token_budget import tokenizer_fingerprint


@dataclass(frozen=True)
class SourceChunk:
    chunk_id: str
    section_path: str
    index: int
    text: str
    context: str
    segments: tuple
    context_segments: tuple
    parent_id: str
    parent_range: tuple
    kind: str
    boundary_split: bool
    context_limited: bool


def _trim(body, start, end):
    while start < end and body[start].isspace(): start += 1
    while end > start and body[end-1].isspace(): end -= 1
    return start, end


def _sections(body):
    headings, start = [], 0
    pattern = re.compile(r"(?m)^(#{1,6})[ \t]+([^\r\n]+)")
    for match in pattern.finditer(body):
        if body[start:match.start()].strip():
            yield tuple(headings), start, match.start()
        level = len(match.group(1))
        headings = [h for h in headings if h[0] < level]
        headings.append((level, match.group(2).strip(), match.start(2), match.start(2)+len(match.group(2).strip())))
        start = match.end()
    if body[start:].strip(): yield tuple(headings), start, len(body)


def _sentences(body, start, end):
    cursor = start
    for match in re.finditer(r"[。！？；!?;](?:[”’\"）)]*)|\n(?=\s*[-*]\s)", body[start:end]):
        stop = start+match.end()
        span = _trim(body, cursor, stop)
        if span[0] < span[1]: yield span
        cursor = stop
    span = _trim(body, cursor, end)
    if span[0] < span[1]: yield span


def _parents(body, start, end):
    """Article sections, QA blocks, and Markdown table rows keep their units."""
    questions = list(re.finditer(r"(?m)^[ \t]*(?:问[：:]|Q[：:])[^\r\n]+", body[start:end]))
    if questions:
        first = start+questions[0].start()
        if body[start:first].strip():
            yield ("article", start, first, (), list(_sentences(body, start, first)))
        for i, question in enumerate(questions):
            a, b = start+question.start(), start+question.end()
            stop = start+questions[i+1].start() if i+1 < len(questions) else end
            units = list(_sentences(body, b, stop))
            yield ("qa", a, stop, ((a, b),), units or [(a, b)])
        return
    blocks = []
    cursor = start
    for match in re.finditer(r"\n[ \t]*\n", body[start:end]):
        stop = start+match.start()
        if body[cursor:stop].strip(): blocks.append(_trim(body, cursor, stop))
        cursor = start+match.end()
    if body[cursor:end].strip(): blocks.append(_trim(body, cursor, end))
    article = []
    def flush():
        if article:
            a, b = article[0][0], article[-1][1]
            article.clear()
            return ("article", a, b, (), list(_sentences(body, a, b)))
    for a, b in blocks:
        raw = body[a:b]
        table = re.search(r"(?m)^\s*\|?\s*:?-{3,}:?\s*\|", raw)
        if table:
            if article: yield flush()
            if table:
                lines = [(a+m.start(), a+m.end()) for m in re.finditer(r"[^\r\n]+", raw)]
                separator = next((i for i, (x, y) in enumerate(lines) if re.fullmatch(r"[\s|:\-]+", body[x:y])), None)
                if separator is not None and separator > 0:
                    # Each row repeats the actual header; offsets retain the
                    # relationship without turning one numeric cell into prose.
                    header = tuple(lines[:separator+1])
                    for row in lines[separator+1:]:
                        yield ("table", a, b, header, [row])
                    continue
            article.append((a, b))
        else:
            article.append((a, b))
    if article: yield flush()


class TokenChunker:
    def __init__(self, tokenizer, *, child_tokens=180, context_tokens=480, overlap_tokens=None,
                 tokenizer_sha256, embedding_tokenizer=None):
        if overlap_tokens is None and type(child_tokens) is int:
            overlap_tokens = min(32, child_tokens//4)
        if (type(child_tokens) is not int or not 64 <= child_tokens <= 220
                or type(context_tokens) is not int or not child_tokens <= context_tokens <= 768
                or type(overlap_tokens) is not int or not 0 <= overlap_tokens < child_tokens//2):
            raise ValueError("invalid token chunk budget")
        self.tokenizer, self.embedding_tokenizer = tokenizer, embedding_tokenizer
        self.child_tokens, self.context_tokens, self.overlap_tokens = child_tokens, context_tokens, overlap_tokens
        self.config = {"strategy": "source_token_parent_child_v1", "child_tokens": child_tokens,
                       "context_tokens": context_tokens, "overlap_tokens": overlap_tokens,
                       "tokenizer_sha256": tokenizer_sha256}
        self.version = "medical-token-v1-"+hashlib.sha256(json.dumps(self.config, sort_keys=True).encode()).hexdigest()[:16]
        self.records = {}

    @classmethod
    def local(cls, **kwargs):
        from transformers import AutoTokenizer
        from .bge_reranker import DEFAULT_MODEL_DIR as rerank_dir
        from .bge_embedding import DEFAULT_MODEL_DIR as embedding_dir
        import os
        rerank_dir = os.getenv("MEDICAL_RERANKER_MODEL_DIR", rerank_dir)
        embedding_dir = os.getenv("MEDICAL_BGE_MODEL_DIR", embedding_dir)
        fingerprints = tokenizer_fingerprint(rerank_dir)+tokenizer_fingerprint(embedding_dir)
        return cls(AutoTokenizer.from_pretrained(rerank_dir, local_files_only=True),
                   embedding_tokenizer=AutoTokenizer.from_pretrained(embedding_dir, local_files_only=True),
                   tokenizer_sha256=hashlib.sha256(fingerprints.encode()).hexdigest(), **kwargs)

    def count(self, text):
        counts = [len(self.tokenizer(text, add_special_tokens=False)["input_ids"])]
        if self.embedding_tokenizer is not None:
            counts.append(len(self.embedding_tokenizer(text, add_special_tokens=False)["input_ids"]))
        return max(counts)

    def _render(self, document, headings, spans):
        text, segments = document.title, []
        # The title is metadata, not source evidence. Actual distinct section
        # headings are copied with verified offsets and never duplicated.
        for _, name, a, b in headings:
            if name in text:
                at = text.index(name)
                segments.append((at, at+len(name), a, b))
                continue
            at = len(text)+1
            text += "\n"+name
            segments.append((at, at+len(name), a, b))
        for a, b in dict.fromkeys(spans):
            if a >= b: continue
            at = len(text)+1
            text += "\n"+document.body[a:b]
            segments.append((at, len(text), a, b))
        return text, tuple(segments)

    def chunks(self, document):
        body, chunks = document.body, []
        for headings, section_start, section_end in _sections(body):
            path = " / ".join(h[1] for h in headings) or document.title
            for kind, parent_start, parent_end, fixed, units in _parents(body, section_start, section_end):
                parent_id = hashlib.sha256(f"{document.doc_id}:{document.version}:{parent_start}:{parent_end}:{body}".encode()).hexdigest()[:24]
                def size(spans): return self.count(self._render(document, headings, tuple(fixed)+tuple(spans))[0])
                # If fixed QA/table structure alone exhausts the budget, fail
                # the candidate build. Never drop the question/table header.
                if size([]) >= self.child_tokens:
                    raise ValueError(f"source header exceeds child budget: {document.doc_id}")
                pieces, split_flags = [], []
                for a, b in units:
                    while size([(a, b)]) > self.child_tokens:
                        # Character binary search, checked with BOTH actual
                        # tokenizers; handles giant sentences without guessing
                        # that one Chinese character equals one token.
                        low, high = a+1, b
                        while low < high:
                            mid = (low+high+1)//2
                            if size([(a, mid)]) <= self.child_tokens: low = mid
                            else: high = mid-1
                        if size([(a, low)]) > self.child_tokens:
                            raise ValueError("one source character exceeds remaining token budget")
                        pieces.append((a, low)); split_flags.append(True); a = low
                    if a < b:
                        pieces.append((a, b)); split_flags.append((a, b) not in units)
                i = 0
                while i < len(pieces):
                    j = i+1
                    while j < len(pieces) and size(pieces[i:j+1]) <= self.child_tokens: j += 1
                    child_spans = tuple(fixed)+tuple(pieces[i:j])
                    text, segments = self._render(document, headings, child_spans)
                    left, right = i, j
                    # Expand whole adjacent source units around the selected
                    # child, bounded by its own parent and section.
                    while left > 0 or right < len(pieces):
                        changed = False
                        if left > 0 and size(pieces[left-1:right]) <= self.context_tokens:
                            left -= 1; changed = True
                        if right < len(pieces) and size(pieces[left:right+1]) <= self.context_tokens:
                            right += 1; changed = True
                        if not changed: break
                    context, context_segments = self._render(document, headings, tuple(fixed)+tuple(pieces[left:right]))
                    key = f"{self.version}:{document.doc_id}:{document.version}:{parent_id}:{child_spans}:{context_segments}"
                    cid = hashlib.sha256(key.encode()).hexdigest()[:32]
                    chunk = SourceChunk(cid, path, len(chunks), text, context, segments, context_segments,
                                        parent_id, (parent_start, parent_end), kind,
                                        any(split_flags[i:j]), left > 0 or right < len(pieces))
                    chunks.append(chunk)
                    self.records[(document.doc_id, cid)] = chunk
                    if j == len(pieces): break
                    # Only repeat a complete short unit, and always advance.
                    overlap = self.count(body[slice(*pieces[j-1])]) <= self.overlap_tokens
                    i = j-1 if overlap and j-1 > i else j
        return chunks
