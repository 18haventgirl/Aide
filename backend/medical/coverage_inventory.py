"""Curated topic backlog plus mechanical source inventory, not clinical review."""
import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path

from .experiment import MEDICAL, digest, repository_version
from .knowledge_base import load_corpus


# Deliberately describe scope gaps, never infer that a keyword mention means a
# complete clinical answer. These references point to existing source IDs only.
TOPICS = [
    ("fever", "发热", "P0", ["NHC-FLU-CARE-20250117", "NHC-HL2024-08", "NHC-HL2024-57"], "已有流感与生命体征资料；缺少普通成人发热的通用观察资料"),
    ("cough", "咳嗽", "P0", ["NHC-HL2024-12", "NHC-HL2024-18"], "侧重持续咳嗽筛查与慢阻肺；缺少常见短期咳嗽的配套科普"),
    ("throat", "咽喉不适", "P0", ["NHC-THROAT-20240821"], "现有节选范围有限，需补充适用人群与就医变化"),
    ("abdomen", "腹痛", "P0", ["GZ-POSTMEAL-ABDOMEN-2026"], "侧重聚餐后腹痛加重；不代表所有腹痛情况均有依据"),
    ("diarrhea", "腹泻", "P0", ["BJ-DIARRHEA-20210406"], "已有脱水与就医信号节选；需补充常见成人情境"),
    ("headache", "头痛", "P0", ["FJ-HEADACHE-20260626"], "已有生活调整/记录/就医信号；需扩展问法和来源"),
    ("dizziness", "头晕", "P0", [], "缺少面向普通成人的专门原文"),
    ("chest", "胸部不适与求助", "P0", ["BJ-EMERG-CHEST-2022", "NHC-HL2024-58"], "侧重求助与信息准备；不用于聊天鉴别诊断"),
    ("sleep", "睡眠", "P0", ["NHC-HL2024-39"], "已有概述；拟补充官方睡眠核心信息的完整结构"),
    ("exercise", "运动与久坐", "P1", ["NHC-HL2024-32"], "已有基本运动量与特殊人群提醒；需更多情境验证"),
    ("nutrition", "膳食营养", "P1", [f"NHC-HL2024-{i}" for i in range(25, 32)]+["NHC-HL2024-54"], "基础素养为主；营养建议需明确人群/单位/来源"),
    ("medication", "一般用药与储存", "P1", ["NHC-HL2024-43", "NHC-HL2024-44", "NHC-HL2024-56"], "现有一般用药资料不能充当具体药物说明书或相互作用库"),
    ("allergy", "常见过敏相关科普", "P1", [], "缺少专门资料；病媒条目中的提及不视为本主题完整覆盖"),
    ("constipation", "便秘相关科普", "P1", [], "缺少专门原文；不以膳食条目代替就医引导"),
    ("backpain", "腰背不适", "P1", [], "缺少专门原文"),
    ("oral", "口腔卫生与不适", "P1", ["NHC-HL2024-41"], "已有口腔卫生；牙痛等具体情况需要独立来源"),
    ("skin", "皮肤不适与皮疹", "P1", [], "缺少专门原文；不进行图片诊断"),
    ("fatigue", "疲劳与一般生活调整", "P2", [], "缺少专门原文，不能将睡眠条目外推为所有疲劳解释"),
    ("mental", "心理健康与寻求帮助", "P1", ["NHC-HL2024-36", "NHC-HL2024-37"], "现有概述不替代专业心理评估"),
]


def inventory(documents, today):
    by_id = {d.doc_id: d for d in documents}
    if len(by_id) != len(documents): raise ValueError("duplicate corpus document IDs")
    missing = {did for _, _, _, ids, _ in TOPICS for did in ids if did not in by_id}
    if missing: raise ValueError(f"backlog bindings changed: {sorted(missing)}")
    urls = Counter(str(d.source_url) for d in documents)
    topics = []
    for topic, name, priority, baseline_ids, gap in TOPICS:
        ids = list(baseline_ids)
        if topic == "sleep" and "NHC-SLEEP-CORE-20250318" in by_id:
            ids.append("NHC-SLEEP-CORE-20250318")
            gap = "已补官方睡眠核心信息的成人子集；仍需多来源和独立情境验证，不等于临床覆盖完整"
        topics.append({"id": topic, "name": name, "priority": priority, "source_ids": ids,
                       "status": "partial_source_scope" if ids else "no_direct_source", "gap": gap,
                       "searchable_source_ids": [did for did in ids if by_id[did].is_searchable(today, research_mode=True)]})
    return {"contract": "curated_topic_inventory_v1", "scope": "curated_source_backlog_not_clinical_completeness_or_retrieval_score",
            "as_of": today.isoformat(), "documents": len(documents), "distinct_source_urls": len(urls),
            "source_concentration": [{"url": url, "documents": count} for url, count in urls.most_common()],
            "eligible_research_documents": sum(d.is_searchable(today, research_mode=True) for d in documents),
            "corpus_sha256": digest([d.model_dump(mode="json") for d in documents]),
            "topics": topics, "topic_status_counts": dict(Counter(t["status"] for t in topics)),
            "notes": ["Shared source corpus does not make held-out question families independent automatically.",
                      "The health-literacy PDF includes age-specific material; chapter-level audience controls remain a governance task.",
                      "Source discovery URLs are not imported/answer-eligible evidence until extraction and provenance checks pass."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--corpus", type=Path, default=MEDICAL/"source_corpus")
    args = parser.parse_args()
    result = inventory(load_corpus(args.corpus), args.as_of)
    result["code"] = repository_version()
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2); handle.write("\n")
    print(json.dumps({"documents": result["documents"], "distinct_source_urls": result["distinct_source_urls"],
                      "topics": result["topic_status_counts"]}))
