"""Small exposed development set for the October Chinese source expansion."""
import argparse
import json
from pathlib import Path

from ..experiment import digest, prepare_origin_contract, validate_source_bindings
from ..knowledge_base import load_corpus
from ..source_provenance import body_hash
from .author_general_v1 import write_frozen


def build_cases(documents, origins):
    docs = {d.doc_id: d for d in documents}
    headache, dizziness, constipation = "FJ-HEADACHE-20260626", "BJ-DIZZINESS-20240301", "BJ-CONSTIPATION-20250331"
    # Integer labels refer to whole source paragraphs; strings are unique exact
    # substrings in the previously frozen headache excerpt. No labels are moved
    # after observing retrieval results.
    specs = [
        (headache, "轻微而短暂的头痛，有哪些生活调整可以先了解？", "headache_gentle_adjustment",
         ["1.先停下来休息，尽量到安静、光线较暗的环境中放松；", "2.补充一些水分，避免空腹；"],
         ["大多数轻度、短暂的头痛，可以先从生活调整入手："], "", "headache"),
        (headache, "头痛经常反复，想记个日记，应该记哪些信息？", "headache_diary_details",
         ["包括发作时间、持续多久、哪里痛、痛到什么程度、有没有恶心怕光、吃了什么、睡得怎么样。"], [], "", "headache"),
        (headache, "没头痛的时候也每天吃止痛药预防，可以吗？", "headache_preventive_painkiller",
         ["5.不要一难受就连续加量吃止痛药，更不要把止痛药当“预防药”天天吃。"], [], "", "headache"),
        (headache, "现在次数越来越多，是否还应该一直自己加药？", "headache_increasing_painkiller",
         ["6.止痛药越吃越频繁，头痛反而越来越多", "这时要警惕药物过度使用性头痛，不建议自己一直加药硬撑。"],
         [], "我最近反复头痛，止痛药也吃得越来越频繁。", "headache"),
        (dizziness, "头晕和周围东西在旋转的感觉有什么区别？", "dizziness_symptom_description", [2, 3], [], "", "dizziness"),
        (dizziness, "发飘、像没睡醒，和天旋地转是一回事吗？", "dizziness_lightheadedness", [4], [], "", "dizziness"),
        (dizziness, "那就能直接认定是颈椎病引起的吗？", "dizziness_cause_uncertainty", [11], [], "我最近经常觉得头晕。", "dizziness"),
        (constipation, "工作时一直坐着不动，和排便困难有没有关系？", "constipation_sedentary_habit", [12], [], "", "constipation"),
        (constipation, "忙起来总忍着便意，长期这样会怎样？", "constipation_suppressed_urge", [13], [], "", "constipation"),
        (constipation, "排便时刷手机、用力憋气，有哪些习惯需要注意？", "constipation_toilet_attention", [40], [], "", "constipation"),
        (constipation, "想了解便秘伴突然剧烈腹痛，或者肚子很胀又不排气时的就医提示。", "constipation_abdominal_warning", [51], [], "", "constipation"),
        (constipation, "服药后顽固便秘，能自己随意加泻药吗？", "constipation_medication_review", [59], [], "", "constipation"),
    ]
    cases = []
    for number, (doc_id, query, family, evidence, conditions, history, topic) in enumerate(specs, 1):
        doc = docs[doc_id]
        def locate(values):
            spans = []
            for value in values:
                if type(value) is int:
                    matches = [p["body_range"] for p in origins[doc_id]["segments"]
                               if p.get("paragraph_index") == value and p["kind"] == "source_text"]
                    if len(matches) != 1: raise ValueError("gold paragraph must have one literal mapping")
                    spans.append(matches[0])
                else:
                    if doc.body.count(value) != 1: raise ValueError("gold quote must be unique")
                    start = doc.body.index(value); spans.append([start, start+len(value)])
            return spans
        row = {"id": f"SCB{number:02d}", "kind": "followup" if history else "supported", "query": query,
               "expected_doc_ids": [doc_id], "expected_evidence": [{"doc_id": doc_id, "version": doc.version,
                   "body_sha256": body_hash(doc.body), "ranges": locate(evidence), "required_conditions": locate(conditions)}],
               "source_binding": {"doc_id": doc_id, "version": doc.version, "source_locator": doc.source_locator,
                                  "normalized_document_sha256": digest(doc.model_dump(mode="json"))},
               "split": "development", "exposed_for_changes": True, "family_id": family,
               "template_id": f"source_batch_20261028_{number:02d}", "topic": topic,
               "authorship": "developer_source_derived_not_external_blind"}
        if history: row["history"] = history
        cases.append(row)
    return cases


def write_batch(snapshot, output):
    documents = load_corpus(snapshot/"corpus")
    origins = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (snapshot/"origins").glob("*.json")}
    cases = build_cases(documents, origins)
    validate_source_bindings(cases, documents)
    prepare_origin_contract("source-evidence-v1", snapshot, snapshot/"corpus", documents, cases)
    write_frozen(output/"source_batch_cases_v1.json", cases)
    pilot = json.loads((output/"source_pilot_cases_v1.json").read_text(encoding="utf-8"))
    manifest = {"schema_version": 1, "hash_scheme": "canonical-json-v1", "suite_id": "aide-source-batch-development-v1",
                "evaluation_date": "2026-10-29", "authorship": "developer_source_derived_not_external_blind",
                "query_contract": "explicit_user_facts_v1", "metric_contract": "source-evidence-v1", "groups": []}
    for name, filename, rows in (("source-batch-development", "source_batch_cases_v1.json", cases),
                                 ("source-origin-pilot-regression", "source_pilot_cases_v1.json", pilot)):
        manifest["groups"].append({"name": name, "purpose": "development", "path": filename, "count": len(rows),
                                   "sha256": digest(rows), "allow_historical_missing_ids": False,
                                   "used_for_changes_after_first_run": True})
    write_frozen(output/"source_batch_suite_v1.json", manifest)
    return {"new_development_cases": len(cases), "prior_pilot_regression": len(pilot), "independent_validation_cases": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(json.dumps(write_batch(args.snapshot, args.output)))
