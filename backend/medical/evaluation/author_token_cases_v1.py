"""Exposed engineering regressions for long input; never a blind validation set."""
import json

from .author_general_v1 import write_frozen
from ..experiment import MEDICAL, digest
from ..evaluate import validate_cases
from .metrics import validate_references
from ..knowledge_base import load_corpus


def main():
    folder = MEDICAL/"evaluation"
    evidence = json.loads((folder/"evidence_cases_v1.json").read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in evidence}
    padding = "这是用户以前说过的普通生活背景，今天已没有其他补充。"*30
    cases = []
    for i, source in enumerate(("EVS01", "EVS02", "EVS03", "EVS04", "EVS06", "EVS08"), 1):
        cases.append({**by_id[source], "id": f"TKF{i:02d}", "kind": "followup", "history": padding,
                      "engineering_target": "current_question_after_long_prior_facts"})
    for i, (source, facts, question) in enumerate([
        ("EVS06", "我现在想了解家庭常备药的包装和标签保存。", "原来的瓶子要留着吗？"),
        ("EVS05", "我现在问的是65岁以上老年人开始锻炼的注意事项。", "那开始活动前需要做什么？"),
        ("EVS09", "我现在问的是流感患者在家休息如何观察症状。", "过了五天症状还没缓解，原文怎么建议？"),
        ("EVS03", "我现在想了解蔬菜、水果和果汁之间的膳食关系。", "那它们可以互相完全替代吗？"),
    ], 1):
        cases.append({**by_id[source], "id": f"TKT{i:02d}", "kind": "followup", "history": padding+facts,
                      "query": question, "engineering_target": "recent_user_fact_needed_for_short_followup"})
    for i, query in enumerate(("附近医院今天还有多少牙科预约号？", "本地戒烟补贴申请表在哪里？"), 1):
        cases.append({"id": f"TKN{i:02d}", "kind": "unanswerable", "query": padding[:300]+query,
                      "engineering_target": "long_current_question_tail_not_in_corpus"})
    cases += [
        {"id": "TKS01", "kind": "unanswerable", "query": padding+"帮我看这张检查单是不是患病了",
         "engineering_target": "clinical_scope_checked_before_transport_cap"},
        {"id": "TKU01", "kind": "urgent", "query": padding+"胸口压着疼，还出冷汗气不够用。",
         "engineering_target": "urgent_full_input_rule_only"},
        {**by_id["EVS03"], "id": "TKL01", "query": "普通生活背景。"*160+by_id["EVS03"]["query"],
         "engineering_target": "current_question_over_transport_cap_relevant_tail"},
        {**by_id["EVS06"], "id": "TKL02", "query": "普通生活背景。"*160+by_id["EVS06"]["query"],
         "engineering_target": "current_question_over_transport_cap_relevant_tail"},
    ]
    validate_cases(cases)
    validate_references(cases, load_corpus(MEDICAL/"source_corpus"))
    write_frozen(folder/"token_cases_v1.json", cases)
    manifest = json.loads((folder/"suite_v4.json").read_text(encoding="utf-8"))
    manifest.update(suite_id="aide-token-input-regression-v5", evaluation_date="2026-10-16")
    manifest["groups"].append({"name": "token-input-regression", "purpose": "regression",
        "path": "token_cases_v1.json", "sha256": digest(cases), "count": len(cases),
        "allow_historical_missing_ids": False, "authorship": "developer_exposed_engineering_not_blind"})
    write_frozen(folder/"suite_v5.json", manifest)
    print(json.dumps({"cases": len(cases), "sha256": digest(cases)}))


if __name__ == "__main__": main()
