"""Small-corpus Chinese BM25 ranking using jieba and rank-bm25."""

import re
import logging

import jieba
from rank_bm25 import BM25Okapi

jieba.setLogLevel(logging.ERROR)


_STOP = frozenset("的 了 是 在 吗 呢 和 有 要 会 可以 怎么 应该 什么 一个 一下 如果 那 我 你 还 就 都 先 能 吗 吧 么 这 个 请 帮".split())


def tokens(text: str) -> list[str]:
    return [word for word in jieba.lcut(text.lower())
            if word not in _STOP and re.search(r"[\u4e00-\u9fffA-Za-z0-9]", word)]


class LexicalIndex:
    def __init__(self, ids: list[str], documents: list[str]):
        self.ids = tuple(ids)
        self.documents = dict(zip(ids, documents))
        self.ranker = BM25Okapi([tokens(document) for document in documents]) if documents else None

    def scores(self, query: str) -> dict[str, float]:
        terms = tokens(query)
        if not terms or self.ranker is None:
            return {item_id: 0.0 for item_id in self.ids}
        return dict(zip(self.ids, self.ranker.get_scores(terms).tolist()))

    def ranked(self, query: str, limit: int) -> list[tuple[str, float]]:
        """Return only positive full-corpus BM25 candidates."""
        scores = self.scores(query)
        return [(item_id, score) for item_id, score in
                sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]
                if score > 0]
