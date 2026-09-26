"""笔记语义检索的召回正确性（离线：不依赖 MySQL、不依赖外网，向量由本地 bge 计算）

其中「植物养护提醒 / 乳制品采购」等查询与语料没有共同用词，用来确认检索是真语义，
而不是关键词匹配；update / delete 用例保证索引跟随内容变化。

语料与 8 组断言是换 langchain-chroma 之前就定下的基线，一字未改：
检索层重构只允许换 API，不允许放宽质量要求。
"""

from langchain_core.documents import Document

CORPUS = {
    "note_gardening": "阳台绿萝浇水记录：土表发白就要浇透，冬天减少到两周一次",
    "note_milk": "超市购物：两升装脱脂牛奶，顺路买鸡蛋和酸奶",
    "note_scramble": "番茄炒蛋做法：先炒蛋再放番茄，加一点糖提鲜",
    "note_report": "季度汇报要点：营收增长百分之十二，续费率下滑需要关注",
    "note_train": "去杭州的高铁：二等座候补成功，早上七点二十发车",
}

QUERIES = [
    ("植物养护提醒", "note_gardening"),      # 与语料零共同用词，纯语义
    ("乳制品采购", "note_milk"),             # 同义改写
    ("鸡蛋做菜的技巧", "note_scramble"),
    ("业务复盘材料", "note_report"),
    ("坐火车去杭州", "note_train"),
    ("超市要买什么", "note_milk"),
    ("给花浇水", "note_gardening"),
    ("番茄炒蛋", "note_scramble"),
]


def _doc(doc_id: str, text: str) -> Document:
    return Document(page_content=text, id=doc_id,
                    metadata={"note_id": doc_id, "title": text[:8]})


def _seed(store):
    store.add_documents([_doc(doc_id, text) for doc_id, text in CORPUS.items()])


def _hit_ids(store, query):
    return [doc.metadata["note_id"] for doc in store.similarity_search(query, k=3)]


def _scores(store, query):
    """取全量候选的相关度，便于断言排序变化而不依赖具体阈值"""
    pairs = store.similarity_search_with_relevance_scores(query, k=len(CORPUS))
    return {doc.metadata["note_id"]: float(score) for doc, score in pairs}


def test_top3_recall_is_correct(rag_store):
    _seed(rag_store)
    misses = []
    for query, expected in QUERIES:
        ids = _hit_ids(rag_store, query)
        if expected not in ids:
            misses.append(f"{query} → 期望 {expected}，实得 {ids}")
    assert not misses, "召回失败:\n" + "\n".join(misses)


def test_update_repoints_relevance(rag_store):
    """改写内容后，向量必须跟着变：同一篇笔记的相关度排序要反转

    不断言"从 top-3 消失"——小语料下旧主题仍可能因语义相近排在前几位，
    真正该钉住的是"新内容比旧主题更相关"。
    """
    _seed(rag_store)
    assert _scores(rag_store, "乳制品采购")["note_milk"] > _scores(rag_store, "猫砂去哪买")["note_milk"]

    rag_store.update_documents(["note_milk"], [_doc("note_milk", "宠物店买猫砂和主食罐头")])

    dairy = _scores(rag_store, "乳制品采购")["note_milk"]
    litter = _scores(rag_store, "猫砂去哪买")["note_milk"]
    assert litter > dairy, f"更新后应更贴合猫砂语境，实得 猫砂={litter:.3f} 乳制品={dairy:.3f}"


def test_delete_removes_from_index(rag_store):
    _seed(rag_store)
    rag_store.delete(ids=["note_milk"])
    assert "note_milk" not in _hit_ids(rag_store, "超市要买什么")
