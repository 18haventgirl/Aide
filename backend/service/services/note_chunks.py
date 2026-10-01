"""Versioned note chunks; offsets always refer to the original body."""
import hashlib
import json
import re

VERSION = "notes-sections-v1"


def revision(note):
    return hashlib.sha256(json.dumps([note.get(k) or "" for k in
        ("user_id", "id", "title", "content", "tag", "status")], ensure_ascii=False).encode()).hexdigest()


def chunks(note, tokenizer, budget=480):
    title = note.get("title") or ""
    body = note.get("content") or ""
    rev = revision(note)
    # Prefix is bounded by the real tokenizer too; the full title remains in SQLite.
    prefix = title
    while len(tokenizer.encode(prefix, add_special_tokens=True)) > 100:
        prefix = prefix[:max(1, len(prefix) // 2)]
    pieces = []
    blocks = [(m.start(),m.end()) for m in re.finditer(r"(?ms)^```[^\n]*\n.*?^```[^\n]*(?:\n|$)|^~~~[^\n]*\n.*?^~~~[^\n]*(?:\n|$)", body)]
    blocks += [(m.start(),m.end()) for m in re.finditer(r"(?m)^(?:[^\n]*\|[^\n]*(?:\n|$)){2,}",body)]
    headings = [m.start() for m in re.finditer(r"(?m)^#{1,6}\s+", body)]
    start = 0
    while start < len(body):
        end = min(start + 400, len(body))
        following = [offset for offset in headings if start < offset < end]
        if following:
            end = following[0]
        for a,b in blocks:
            if b-a<=400 and a<end<b:
                end = a if a>start else b
        if end < len(body):
            candidates = [m.end() + start for m in re.finditer(r"\n|[。！？；]", body[start:end])]
            if candidates and candidates[-1] > start + 150 and end not in {b for a,b in blocks}:
                end = candidates[-1]
        while len(tokenizer.encode(prefix + "\n" + body[start:end], add_special_tokens=True)) > budget:
            end = start + max(1, (end - start) // 2)
            if end == start + 1:
                break
        text = prefix + "\n" + body[start:end]
        if len(tokenizer.encode(text, add_special_tokens=True)) > budget:
            raise ValueError("note token budget exceeded")
        pieces.append((start, end, text))
        if end == len(body):
            break
        # Overlap only at a sentence boundary; never discard any source characters.
        tail = [m.end() + start for m in re.finditer(r"\n|[。！？；]", body[start:end])]
        overlap = [x for x in tail if end - 50 <= x < end and x > start]
        start = overlap[0] if overlap and end not in headings else end
    if not pieces:
        pieces = [(0, 0, prefix)]
    return [{"id": hashlib.sha256(f"{VERSION}:{note['user_id']}:{note['id']}:{rev}:{a}:{b}".encode()).hexdigest(),
             "revision": rev, "start": a, "end": b, "text": text} for a, b, text in pieces]
