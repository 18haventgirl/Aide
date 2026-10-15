"""Author source-range regression labels without rewriting exposed datasets."""
import json
from .author_general_v1 import write_frozen
from ..experiment import MEDICAL, digest
from ..knowledge_base import load_corpus
from ..source_provenance import body_hash
from .metrics import validate_references
from ..evaluate import validate_cases


ROWS = [
    ("鼠夹、防鼠网和封堵孔洞，分别怎样帮助防鼠卫生？", "NHC-HL2024-14", ["安装防鼠门、防鼠网、封堵孔洞等。", "杀灭老鼠可以使用鼠夹、鼠笼、粘鼠板等捕鼠工具"], []),
    ("防护用品戴一会儿就好，暴露作业时不必全程使用吧？", "NHC-HL2024-23", ["在工作期间全程、规范使用防护用品。"], ["劳动者应知晓本人所在的工作环境及工作过程中存在的职业病危害因素"]),
    ("水果、蔬菜和果汁可以互相完全替代吗？", "NHC-HL2024-26", ["蔬菜和水果不能相互替换，果汁不能代替水果。"], []),
    ("健康成年人一周应该做多久有氧活动？", "NHC-HL2024-32", ["建议健康成年人每周应进行150～300分钟中等强度或75～150分钟高强度有氧运动。"], ["建议健康成年人每周应进行"]),
    ("老年人和慢性病患者在运动前应该关注哪些准备？", "NHC-HL2024-32", ["身体活动前应咨询医生，并在专业人员指导下进行。"], ["65岁以上老年人、慢性疾病患者"]),
    ("家庭常备药的药瓶和标签应该保留吗？", "NHC-HL2024-56", ["药品应保存在原始包装中，不要将瓶外标签撕掉。"], []),
    ("家里的药过期后可以随便丢掉吗？", "NHC-HL2024-56", ["过期和变质药品不能随意丢弃，按照有害垃圾处理。"], ["药品按说明书要求妥善存放"]),
    ("一般腹泻出现什么变化应该及时去肠道门诊？", "BJ-DIARRHEA-20210406", ["请您及时于设有肠道门诊的医疗机构就诊"], ["如果出现发热、频繁的呕吐和腹泻、吐泻量较大、便中带脓血、基础病加重等严重情况"]),
    ("流感发病后症状一直不缓解，资料里如何建议就医？", "NHC-FLU-CARE-20250117", ["发病以后如果超过5天症状没有缓解趋势，也建议及时就医。"], ["流感发热：需要就医的变化"]),
    ("聚餐后腹痛持续加重伴呕吐，原文有哪些就医提示？", "GZ-POSTMEAL-ABDOMEN-2026", ["建议立即到附近医院的急诊科就诊。"], ["如果疼痛在短时间内持续加重，同时出现高热、频繁呕吐、腹胀明显"]),
    ("反复头痛为什么建议记头痛日记，要记录哪些信息？", "FJ-HEADACHE-20260626", ["建议记一记“头痛日记”，包括发作时间、持续多久、哪里痛、痛到什么程度、有没有恶心怕光、吃了什么、睡得怎么样。"], ["如果头痛总在某些场景反复出现"]),
    ("干燥空气和鼻塞后张口呼吸为什么可能引起咽喉不适？", "NHC-THROAT-20240821", ["鼻塞以后就张口呼吸，不洁的空气和干燥的空气，直接刺激咽喉部"], []),
]


def span(body, anchor):
    start = body.find(anchor)
    if start < 0 or body.find(anchor, start+1) >= 0:
        raise ValueError("missing or ambiguous source anchor")
    return [start, start + len(anchor)]


def main():
    docs = load_corpus(MEDICAL / "source_corpus")
    by_id = {doc.doc_id: doc for doc in docs}
    cases = []
    for i, (query, did, anchors, conditions) in enumerate(ROWS, 1):
        doc = by_id[did]
        cases.append({"id": f"EVS{i:02d}", "kind": "supported", "query": query,
                      "expected_doc_ids": [did], "expected_evidence": [{"doc_id": did, "version": doc.version,
                          "body_sha256": body_hash(doc.body), "ranges": [span(doc.body, a) for a in anchors],
                          "required_conditions": [span(doc.body, a) for a in conditions]}]})
    for i, (source, history, question) in enumerate([
        (5, "我在看家庭常备药的包装保存。", "原来的瓶子要留着吗？"),
        (4, "我在了解65岁以上老年人运动。", "那开始活动前需要做什么？"),
        (8, "我问的是流感居家休息时的变化。", "过了五天症状还没缓解，资料怎么说？"),
        (2, "我在看蔬菜水果的膳食科普。", "那果汁可以完全替代吗？"),
    ], 1):
        reference = cases[source]
        cases.append({**reference, "id": f"EVF{i:02d}", "kind": "followup", "history": history, "query": question})
    for i, query in enumerate(["献血者血型决定星座运势吗？", "本地戒烟补贴申请表在哪里？", "体重秤固件怎么更新？", "附近医院今天还有多少牙科预约号？"], 1):
        cases.append({"id": f"EVN{i:02d}", "kind": "unanswerable", "query": query})
    for i, query in enumerate(["胸口压着疼，还出冷汗气不够用。", "刚才讲话含糊，一只胳膊抬不起来，脸也歪了。", "这次头痛突然特别剧烈，而且一直吐。", "现在呼吸越来越困难，一句完整的话都说不出来。"], 1):
        cases.append({"id": f"EVU{i:02d}", "kind": "urgent", "query": query})
    validate_cases(cases)
    validate_references(cases, docs)
    directory = MEDICAL / "evaluation"
    write_frozen(directory / "evidence_cases_v1.json", cases)
    manifest = json.loads((directory / "suite_v3.json").read_text(encoding="utf-8"))
    manifest.update(suite_id="aide-evidence-budget-v4", evaluation_date="2026-10-15")
    manifest["groups"].append({"name": "evidence-regression", "purpose": "regression",
                              "path": "evidence_cases_v1.json", "sha256": digest(cases), "count": len(cases),
                              "allow_historical_missing_ids": False,
                              "authorship": "developer_source_ranges_exposed_regression_not_blind"})
    write_frozen(directory / "suite_v4.json", manifest)
    print(json.dumps({"cases": len(cases), "sha256": digest(cases)}))


if __name__ == "__main__": main()
