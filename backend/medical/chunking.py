"""Chinese-aware section and sentence chunking.

Chunks carry their heading path in the indexed text; overlap is measured in
characters and never crosses a document or a heading boundary.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    section_path: str
    text: str
    index: int


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SENTENCES = re.compile(r"(?<=[。！？；!?;])")


def _sections(body: str, title: str):
    path: list[str] = []
    paragraphs: list[str] = []

    def flush():
        if paragraphs:
            yield " / ".join(path) if path else title, "\n".join(paragraphs)

    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            if paragraphs and paragraphs[-1] != "":
                paragraphs.append("")
            continue
        match = _HEADING.match(line)
        if match:
            yield from flush()
            paragraphs.clear()
            level = len(match.group(1))
            path = path[: level - 1] + [match.group(2)]
        else:
            paragraphs.append(line)
    yield from flush()


def _split_long_text(text: str, max_chars: int) -> list[str]:
    """Split on Chinese sentence ends, falling back to hard cuts for long spans."""
    pieces: list[str] = []
    for sentence in _SENTENCES.split(text):
        sentence = sentence.strip()
        while len(sentence) > max_chars:
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if sentence:
            pieces.append(sentence)
    return pieces


def chunk_document(body: str, title: str, max_chars: int = 600, overlap: int = 80) -> list[TextChunk]:
    if max_chars < 100 or not 0 <= overlap < max_chars:
        raise ValueError("invalid chunk size or overlap")
    output: list[TextChunk] = []
    for section_path, section in _sections(body, title):
        parts = _split_long_text(section, max_chars)
        current = ""
        section_index = 0
        for part in parts:
            if current and len(current) + 1 + len(part) > max_chars:
                output.append(TextChunk(section_path, current.strip(), section_index))
                section_index += 1
                # Keep a short tail to maintain context without crossing sections.
                current = current[-overlap:] if overlap else ""
                if len(current) + 1 + len(part) > max_chars:
                    current = ""
            current += ("\n" if current else "") + part
        if current.strip():
            output.append(TextChunk(section_path, current.strip(), section_index))
    return output
