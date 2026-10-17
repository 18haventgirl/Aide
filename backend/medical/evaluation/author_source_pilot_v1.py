"""Source-derived development pilot; not the planned held-out evaluation set."""
import argparse
from pathlib import Path

from ..experiment import digest, prepare_origin_contract, validate_source_bindings
from ..knowledge_base import load_corpus
from ..source_provenance import body_hash
from .author_general_v1 import write_frozen


def build_cases(documents):
    by_id = {d.doc_id: d for d in documents}
    sleep = "NHC-SLEEP-CORE-20250318"
    abdomen = "GZ-POSTMEAL-ABDOMEN-2026"
    specs = [
        (sleep, "成年人是不是每天必须正好睡满八小时？", "sleep_duration_variation",
         ["一般来说，成年人7-8小时，老年人6-7小时。"],
         ["不同年龄段人群对睡眠时长的需求不同，且存在个体差异。"], ""),
        (sleep, "判断睡得好不好，除了时长还应该关注什么？", "sleep_quality_signs",
         ["良好睡眠质量通常表现为：入睡时间在30分钟以内；夜间醒来的次数不超过3次，且醒来后能在20分钟内再次入睡；醒来后感到精神饱满、心情愉悦、精力充沛、注意力集中。"], [], ""),
        (sleep, "睡眠时间经常变来变去，只要总时长够就可以了吗？", "sleep_schedule_consistency",
         ["保持规律的入睡和起床时间，维持稳定的生物节律"], [], ""),
        (sleep, "睡前喝咖啡、吃得太饱和刷手机，会不会影响入睡？", "sleep_evening_habits",
         ["熬夜，睡前长时间使用电子产品，晚饭过饱过晚，睡前吸烟、饮酒、喝茶或咖啡，睡前长时间剧烈运动等，都会对睡眠产生不良影响。"], [], ""),
        (sleep, "为了睡得好些，卧室环境有哪些可以改善的地方？", "sleep_environment",
         ["卧室环境应安静舒适，根据个人的习惯保持适宜的光线强度，室内温度在20℃-24℃、空气湿度在40%-60%为宜，经常开窗通风。"], [], ""),
        (sleep, "工作压力大，经常熬夜，想了解与睡眠相关的日常调整。", "sleep_occupational_stress",
         ["职业人群应妥善管理自己的工作时间，尽量避免熬夜，防止过度疲劳。", "学会缓解工作压力，保持心态平和，必要时可寻求专业的心理咨询或治疗。"], [], ""),
        (sleep, "老人一晚没睡好就非常焦虑，关于睡眠期望有什么提醒？", "sleep_older_adult_expectations",
         ["保持合理的睡眠期望，不把所有的问题都归咎于失眠，不过分关注睡眠，不因为一晚没睡好就产生焦虑情绪。"],
         ["老年人维持睡眠能力下降，更易发生睡眠障碍。"], ""),
        (sleep, "睡觉鼾声很响，家人还发现会停顿，这种情况需要求助吗？", "sleep_breathing_help",
         ["夜间鼾声响亮伴有呼吸间歇", "应及时到医疗机构寻求专业帮助。"], [], ""),
        (sleep, "已经影响白天的工作了，应该怎么办？", "sleep_daily_function_help",
         ["如果睡眠问题已影响到健康和日常的工作生活，应尽早去医疗机构寻求专业帮助"], [],
         "我最近经常入睡困难，夜里也反复醒来。"),
        (abdomen, "聚餐后腹痛越来越重，还发高烧、反复呕吐，原资料有哪些就医提示？", "postmeal_abdominal_warning",
         ["如果疼痛在短时间内持续加重，同时出现高热、频繁呕吐、腹胀明显，甚至有心率加快、呼吸急促的症状，建议立即到附近医院的急诊科就诊。"], [], ""),
        (abdomen, "聚餐后肚子痛，能不能自己多吃止痛药硬撑？", "postmeal_painkiller_caution",
         ["特别提醒，不建议患者吃止痛药硬扛，以免掩盖病情、延误诊治。"], [], ""),
        (abdomen, "现在疼痛持续加重，还不停吐，有什么求助提示？", "postmeal_abdominal_warning",
         ["如果疼痛在短时间内持续加重，同时出现高热、频繁呕吐、腹胀明显，甚至有心率加快、呼吸急促的症状，建议立即到附近医院的急诊科就诊。"], [],
         "我刚才聚餐后突然肚子痛。"),
    ]
    cases = []
    for index, (doc_id, query, family, evidence, conditions, history) in enumerate(specs, 1):
        doc = by_id[doc_id]
        def ranges(texts):
            spans = []
            for text in texts:
                if doc.body.count(text) != 1:
                    raise ValueError(f"pilot source selection is not uniquely located: {doc_id}")
                start = doc.body.index(text)
                spans.append([start, start+len(text)])
            return spans
        case = {"id": f"SOP{index:02d}", "kind": "followup" if history else "supported", "query": query,
                "expected_doc_ids": [doc_id], "expected_evidence": [{"doc_id": doc_id, "version": doc.version,
                    "body_sha256": body_hash(doc.body), "ranges": ranges(evidence), "required_conditions": ranges(conditions)}],
                "source_binding": {"doc_id": doc_id, "version": doc.version, "source_locator": doc.source_locator,
                    "normalized_document_sha256": digest(doc.model_dump(mode="json"))},
                "split": "development", "exposed_for_changes": True, "family_id": family,
                "template_id": f"source_pilot_{index:02d}", "topic": "sleep" if doc_id == sleep else "postmeal_abdominal_pain",
                "authorship": "developer_source_derived_not_external_blind"}
        if history: case["history"] = history
        cases.append(case)
    return cases


def write_pilot(snapshot, output):
    documents = load_corpus(snapshot/"corpus")
    cases = build_cases(documents)
    validate_source_bindings(cases, documents)
    prepare_origin_contract("source-evidence-v1", snapshot, snapshot/"corpus", documents, cases)
    write_frozen(output/"source_pilot_cases_v1.json", cases)
    manifest = {"schema_version": 1, "hash_scheme": "canonical-json-v1", "suite_id": "aide-source-origin-development-pilot-v1",
                "evaluation_date": "2026-10-17", "authorship": "developer_source_derived_not_external_blind",
                "query_contract": "explicit_user_facts_v1", "metric_contract": "source-evidence-v1",
                "groups": [{"name": "source-origin-pilot-development", "purpose": "development",
                    "path": "source_pilot_cases_v1.json", "count": len(cases), "sha256": digest(cases),
                    "allow_historical_missing_ids": False, "used_for_changes_after_first_run": True}]}
    write_frozen(output/"source_pilot_suite_v1.json", manifest)
    return {"cases": len(cases), "authorship": manifest["authorship"], "metric_contract": manifest["metric_contract"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(write_pilot(args.snapshot, args.output))
