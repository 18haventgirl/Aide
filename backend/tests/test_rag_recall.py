"""自研 RAG 的召回正确性（离线：不依赖 MySQL、不依赖外网，向量由本地 bge 计算）

其中「植物养护提醒 / 乳制品采购」等查询与语料没有共同用词，用来确认检索是真语义，
而不是关键词匹配；update / delete 用例保证索引跟随内容变化。
"""

from core.vector_core.models import VectorDeleteFilter, VectorDocument, VectorQuery

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


def _seed(rag_client):
    for doc_id, text in CORPUS.items():
        rag_client.add_document(VectorDocument(
            id=doc_id, text=text, user_id="tester", source="notes",
            metadata={"note_id": doc_id}))


def _hit_ids(rag_client, query):
    results = rag_client.query_documents(VectorQuery(
        query_text=query, user_id="tester", limit=3, source_filter="notes",
        include_metadata=True, include_distances=True))
    return [result.id for result in results]


def _scores(rag_client, query):
    """取全量候选的相关度，便于断言排序变化而不依赖具体阈值"""
    results = rag_client.query_documents(VectorQuery(
        query_text=query, user_id="tester", limit=len(CORPUS), source_filter="notes",
        include_metadata=True, include_distances=True))
    return {result.id: (result.score or 0.0) for result in results}


def test_top3_recall_is_correct(rag_client):
    _seed(rag_client)
    misses = []
    for query, expected in QUERIES:
        ids = _hit_ids(rag_client, query)
        if expected not in ids:
            misses.append(f"{query} → 期望 {expected}，实得 {ids}")
    assert not misses, "召回失败:\n" + "\n".join(misses)


def test_update_repoints_relevance(rag_client):
    """改写内容后，向量必须跟着变：同一篇笔记的相关度排序要反转

    不断言"从 top-3 消失"——小语料下旧主题仍可能因语义相近排在前几位，
    真正该钉住的是"新内容比旧主题更相关"。
    """
    _seed(rag_client)
    assert _scores(rag_client, "乳制品采购")["note_milk"] > _scores(rag_client, "猫砂去哪买")["note_milk"]

    rag_client.update_document("note_milk", "tester",
                               text="宠物店买猫砂和主食罐头", metadata={"note_id": "note_milk"})

    dairy = _scores(rag_client, "乳制品采购")["note_milk"]
    litter = _scores(rag_client, "猫砂去哪买")["note_milk"]
    assert litter > dairy, f"更新后应更贴合猫砂语境，实得 猫砂={litter:.3f} 乳制品={dairy:.3f}"


def test_delete_removes_from_index(rag_client):
    _seed(rag_client)
    rag_client.delete_documents(VectorDeleteFilter(user_id="tester", document_ids=["note_milk"]))
    assert "note_milk" not in _hit_ids(rag_client, "超市要买什么")
