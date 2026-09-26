"""笔记 ↔ LangChain Document 的映射

id 规则沿用旧的 note_{id}，删除与更新才可能对得上既有集合。
documents_to_rows 的输出键就是 REST 契约（note_id/title/tag/score/text），不改形状。
"""

from typing import Any, Dict, Iterable, List, Tuple

from langchain_core.documents import Document

SNIPPET_CHARS = 500


def note_document(note: Any) -> Document:
    title = getattr(note, "title", "") or ""
    content = getattr(note, "content", "") or ""
    return Document(
        page_content=f"{title}\n{content}",
        id=f"note_{note.id}",
        metadata={
            "note_id": str(note.id),
            "user_id": str(getattr(note, "user_id", "") or ""),
            "title": title,
            "tag": getattr(note, "tag", "") or "",
            "status": getattr(note, "status", "") or "",
            "source": "notes",
        },
    )


def documents_to_rows(pairs: Iterable[Tuple[Document, float]],
                      threshold: float) -> List[Dict[str, Any]]:
    rows = []
    for doc, score in pairs:
        if float(score) < threshold:
            continue
        meta = doc.metadata or {}
        rows.append({
            "note_id": meta.get("note_id"),
            "title": meta.get("title"),
            "tag": meta.get("tag") or None,
            "score": float(score),
            "text": doc.page_content[:SNIPPET_CHARS],
        })
    return rows
