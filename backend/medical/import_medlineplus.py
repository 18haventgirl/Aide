"""Import a small, pinned set of MedlinePlus health topics for local RAG.

The raw daily XML stays in ``source_downloads`` (gitignored). Generated JSON
records retain the official English summary and add only Chinese retrieval
labels; no machine-translated medical prose is stored as source evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

from .schema import MedicalDocument
from .data_registry import assert_answer_eligible


BASE = Path(__file__).resolve().parent
DEFAULT_ARCHIVE = BASE / "source_downloads" / "mplus_topics_compressed_2026-09-19.zip"
DEFAULT_OUTPUT = BASE / "source_corpus"
ARCHIVE_SHA256 = "4b52e1a2c4c499d363dfbff1776875b53a695b315e7761e1c283b223b675ed74"
SOURCE_DATE = date(2026, 9, 19)
SOURCE_DOWNLOAD_URL = "https://medlineplus.gov/xml/mplus_topics_compressed_2026-09-19.zip"
SOURCE_CHECKER = "Aide MedlinePlus importer (automated source parsing; non-clinician)"

# A deliberately bounded set of common adult symptoms. Chinese terms are
# retrieval labels rather than translations of the evidence body.
TOPICS = {
    "3061": {"slug": "abdominal-pain", "title": "腹痛（Abdominal Pain）", "topic": "腹痛", "aliases": "肚子痛、肚子疼、腹部疼痛、胃疼"},
    "196": {"slug": "common-cold", "title": "普通感冒（Common Cold）", "topic": "普通感冒", "aliases": "感冒、鼻塞、流鼻涕"},
    "1543": {"slug": "cough", "title": "咳嗽（Cough）", "topic": "咳嗽", "aliases": "咳嗽、干咳、咳痰"},
    "211": {"slug": "diarrhea", "title": "腹泻（Diarrhea）", "topic": "腹泻", "aliases": "拉肚子、稀便、水样便"},
    "511": {"slug": "fever", "title": "发热（Fever）", "topic": "发热", "aliases": "发烧、体温升高、低烧、高烧"},
    "273": {"slug": "headache", "title": "头痛（Headache）", "topic": "头痛", "aliases": "头疼、头部疼痛、偏头痛"},
    "489": {"slug": "nausea-vomiting", "title": "恶心与呕吐（Nausea and Vomiting）", "topic": "恶心呕吐", "aliases": "恶心、想吐、呕吐、吐了"},
    "4748": {"slug": "sore-throat", "title": "咽痛（Sore Throat）", "topic": "咽痛", "aliases": "嗓子疼、喉咙痛、咽喉疼痛"},
    "216": {"slug": "dizziness-vertigo", "title": "头晕与眩晕（Dizziness and Vertigo）", "topic": "头晕眩晕", "aliases": "头晕、眩晕、天旋地转、站不稳"},
    "208": {"slug": "rashes", "title": "皮疹（Rashes）", "topic": "皮疹", "aliases": "皮疹、红疹、身上起疹子、皮肤发红"},
    "157": {"slug": "back-pain", "title": "背痛（Back Pain）", "topic": "背痛", "aliases": "背疼、腰背痛、后背疼痛"},
    "4744": {"slug": "chest-pain", "title": "胸痛（Chest Pain）", "topic": "胸痛", "aliases": "胸痛、胸口疼、胸部疼痛、胸闷"},
    "3077": {"slug": "breathing-problems", "title": "呼吸问题（Breathing Problems）", "topic": "呼吸问题", "aliases": "呼吸困难、喘不过气、气短、呼吸费劲"},
    "5324": {"slug": "fatigue", "title": "疲劳（Fatigue）", "topic": "疲劳", "aliases": "乏力、疲倦、总觉得累、没精神"},
    "200": {"slug": "constipation", "title": "便秘（Constipation）", "topic": "便秘", "aliases": "便秘、排便困难、大便干、很久不排便"},
    "1653": {"slug": "heartburn", "title": "烧心（Heartburn）", "topic": "烧心", "aliases": "烧心、反酸、胃酸、胸口灼热"},
    "448": {"slug": "urinary-tract-infections", "title": "尿路感染（Urinary Tract Infections）", "topic": "尿路感染", "aliases": "尿痛、尿频、尿急、小便刺痛"},
    "4293": {"slug": "indigestion", "title": "消化不良（Indigestion）", "topic": "消化不良", "aliases": "消化不良、饭后胀、胃胀、嗳气"},
}

# Adult-facing prevention, chronic condition, nutrition, and common symptom
# topics selected from the pinned official XML. Aliases aid Chinese retrieval;
# they do not replace or translate the NLM-authored English evidence.
EXPANSION_TOPICS = {
    "6601": {"slug": "benefits-of-exercise", "title": "运动的益处（Benefits of Exercise）", "topic": "运动", "aliases": "运动有什么好处、体育锻炼、活动身体"},
    "6603": {"slug": "how-much-exercise", "title": "运动量（How Much Exercise Do I Need?）", "topic": "运动量", "aliases": "每周运动多久、运动时长、锻炼多长时间"},
    "490": {"slug": "exercise-physical-fitness", "title": "运动与体能（Exercise and Physical Fitness）", "topic": "运动健身", "aliases": "健身、锻炼、体育活动"},
    "6469": {"slug": "healthy-sleep", "title": "健康睡眠（Healthy Sleep）", "topic": "睡眠", "aliases": "睡眠、睡多久、睡眠质量"},
    "408": {"slug": "sleep-disorders", "title": "睡眠障碍（Sleep Disorders）", "topic": "睡眠障碍", "aliases": "失眠、睡不着、睡眠问题"},
    "422": {"slug": "stress", "title": "压力（Stress）", "topic": "压力", "aliases": "压力大、紧张、心理压力"},
    "144": {"slug": "anxiety", "title": "焦虑（Anxiety）", "topic": "焦虑", "aliases": "焦虑、担心、心慌紧张"},
    "113": {"slug": "depression", "title": "抑郁（Depression）", "topic": "抑郁", "aliases": "情绪低落、抑郁、提不起精神"},
    "34": {"slug": "high-blood-pressure", "title": "高血压（High Blood Pressure）", "topic": "高血压", "aliases": "血压高、高血压、血压升高"},
    "4": {"slug": "diabetes", "title": "糖尿病（Diabetes）", "topic": "糖尿病", "aliases": "糖尿病、血糖高、血糖"},
    "5930": {"slug": "diabetes-type-2", "title": "2型糖尿病（Diabetes Type 2）", "topic": "2型糖尿病", "aliases": "二型糖尿病、成人糖尿病、血糖高"},
    "5784": {"slug": "prediabetes", "title": "糖尿病前期（Prediabetes）", "topic": "糖尿病前期", "aliases": "血糖偏高、糖尿病前期、空腹血糖异常"},
    "26": {"slug": "cholesterol", "title": "胆固醇（Cholesterol）", "topic": "胆固醇", "aliases": "血脂、胆固醇、高胆固醇"},
    "6781": {"slug": "cholesterol-levels", "title": "胆固醇水平（Cholesterol Levels）", "topic": "胆固醇水平", "aliases": "血脂报告、胆固醇指标、血脂偏高"},
    "277": {"slug": "heart-diseases", "title": "心脏病（Heart Diseases）", "topic": "心脏疾病", "aliases": "心脏病、心血管疾病、心脏问题"},
    "8": {"slug": "stroke", "title": "脑卒中（Stroke）", "topic": "脑卒中", "aliases": "中风、脑卒中、脑血管意外"},
    "24": {"slug": "allergy", "title": "过敏（Allergy）", "topic": "过敏", "aliases": "过敏、过敏反应、皮肤过敏"},
    "2": {"slug": "asthma", "title": "哮喘（Asthma）", "topic": "哮喘", "aliases": "哮喘、喘息、喘不过气"},
    "299": {"slug": "flu", "title": "流感（Flu）", "topic": "流感", "aliases": "流行性感冒、流感、发烧咳嗽"},
    "6051": {"slug": "dehydration", "title": "脱水（Dehydration）", "topic": "脱水", "aliases": "脱水、缺水、口干尿少"},
    "28": {"slug": "dental-health", "title": "口腔健康（Dental Health）", "topic": "口腔健康", "aliases": "牙齿健康、口腔卫生、牙疼"},
    "36": {"slug": "nutrition", "title": "营养（Nutrition）", "topic": "营养", "aliases": "营养、健康饮食、均衡饮食"},
    "61": {"slug": "obesity", "title": "肥胖（Obesity）", "topic": "肥胖", "aliases": "肥胖、体重超标、减重"},
    "1434": {"slug": "food-safety", "title": "食品安全（Food Safety）", "topic": "食品安全", "aliases": "食物安全、食品卫生、食物变质"},
    "254": {"slug": "foodborne-illness", "title": "食源性疾病（Foodborne Illness）", "topic": "食源性疾病", "aliases": "食物中毒、吃坏肚子、食源性疾病"},
    "1256": {"slug": "food-allergy", "title": "食物过敏（Food Allergy）", "topic": "食物过敏", "aliases": "吃东西过敏、食物过敏、过敏原"},
    "1558": {"slug": "alcohol", "title": "饮酒（Alcohol）", "topic": "饮酒", "aliases": "喝酒、饮酒、酒精"},
    "108": {"slug": "smoking", "title": "吸烟（Smoking）", "topic": "吸烟", "aliases": "抽烟、吸烟、烟草"},
    "1359": {"slug": "quitting-smoking", "title": "戒烟（Quitting Smoking）", "topic": "戒烟", "aliases": "戒烟、停止吸烟、烟瘾"},
    "294": {"slug": "vaccines", "title": "疫苗（Vaccines）", "topic": "疫苗", "aliases": "疫苗、预防接种、打疫苗"},
    "6236": {"slug": "flu-shot", "title": "流感疫苗（Flu Shot）", "topic": "流感疫苗", "aliases": "流感疫苗、预防流感、流感接种"},
    "23": {"slug": "arthritis", "title": "关节炎（Arthritis）", "topic": "关节炎", "aliases": "关节疼、关节炎、关节肿"},
    "1250": {"slug": "osteoarthritis", "title": "骨关节炎（Osteoarthritis）", "topic": "骨关节炎", "aliases": "骨关节炎、膝关节疼、关节磨损"},
    "5987": {"slug": "chronic-kidney-disease", "title": "慢性肾病（Chronic Kidney Disease）", "topic": "慢性肾病", "aliases": "肾功能下降、慢性肾病、肾脏病"},
    "1224": {"slug": "kidney-stones", "title": "肾结石（Kidney Stones）", "topic": "肾结石", "aliases": "肾结石、尿路结石、腰痛血尿"},
    "91": {"slug": "kidney-diseases", "title": "肾脏疾病（Kidney Diseases）", "topic": "肾脏疾病", "aliases": "肾病、肾脏疾病、肾功能问题"},
    "3157": {"slug": "migraine", "title": "偏头痛（Migraine）", "topic": "偏头痛", "aliases": "偏头痛、反复头痛、单侧头痛"},
    "40": {"slug": "skin-conditions", "title": "皮肤问题（Skin Conditions）", "topic": "皮肤问题", "aliases": "皮肤病、皮肤问题、皮肤不适"},
    "5358": {"slug": "skin-infections", "title": "皮肤感染（Skin Infections）", "topic": "皮肤感染", "aliases": "皮肤感染、皮肤红肿、化脓"},
    "5798": {"slug": "dry-mouth", "title": "口干（Dry Mouth）", "topic": "口干", "aliases": "口干、嘴巴干、口腔干燥"},
    "3756": {"slug": "food-labeling", "title": "食品标签（Food Labeling）", "topic": "食品标签", "aliases": "营养标签、食品标签、配料表"},
    "6807": {"slug": "lower-cholesterol-diet", "title": "饮食与胆固醇（How to Lower Cholesterol with Diet）", "topic": "饮食与血脂", "aliases": "降血脂饮食、胆固醇饮食、血脂高怎么吃"},
    "6661": {"slug": "prevent-diabetes", "title": "预防糖尿病（How to Prevent Diabetes）", "topic": "糖尿病预防", "aliases": "预防糖尿病、降低糖尿病风险"},
    "1598": {"slug": "prevent-heart-disease", "title": "预防心脏病（How to Prevent Heart Disease）", "topic": "心脏病预防", "aliases": "预防心脏病、保护心脏、心血管预防"},
    "6450": {"slug": "prevent-high-blood-pressure", "title": "预防高血压（How to Prevent High Blood Pressure）", "topic": "高血压预防", "aliases": "预防高血压、如何控制血压、降压生活方式"},
    "1530": {"slug": "exercise-older-adults", "title": "老年人运动（Exercise for Older Adults）", "topic": "老年人运动", "aliases": "老人锻炼、老年运动、老年人活动"},
    "1616": {"slug": "nutrition-older-adults", "title": "老年人营养（Nutrition for Older Adults）", "topic": "老年人营养", "aliases": "老人饮食、老年营养、老年人怎么吃"},
    "4224": {"slug": "fluid-electrolytes", "title": "体液与电解质（Fluid and Electrolyte Balance）", "topic": "体液与电解质", "aliases": "电解质、补水、出汗后补水"},
    "5461": {"slug": "malnutrition", "title": "营养不良（Malnutrition）", "topic": "营养不良", "aliases": "营养不良、吃不够、营养缺乏"},
    "7667": {"slug": "vaccine-safety", "title": "疫苗安全（Vaccine Safety）", "topic": "疫苗安全", "aliases": "疫苗安全、接种反应、打疫苗风险"},
}
TOPICS.update(EXPANSION_TOPICS)


class SummaryText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "li":
            self.parts.append("\n- ")
        elif tag.lower() in {"h1", "h2", "h3"}:
            # Topic summaries often start at h3 with no h2 parent. Flatten
            # h2/h3 into sibling subheadings so the generic section splitter
            # does not accidentally nest one audience under another.
            self.parts.append("\n" + ("#" if tag.lower() == "h1" else "##") + " ")
        elif tag.lower() in {"p", "br", "ul", "ol"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "li", "ul", "ol", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def summary_text(element: ET.Element) -> str:
    parser = SummaryText()
    # MedlinePlus stores summary markup as escaped text, while fixtures and
    # compatible feeds may expose real child elements. Handle both forms.
    if list(element):
        markup = "".join(ET.tostring(child, encoding="unicode", method="html") for child in element)
    else:
        markup = element.text or ""
    parser.feed(markup)
    return parser.text()


def build_documents(xml_bytes: bytes, collected_at: date) -> list[MedicalDocument]:
    root = ET.fromstring(xml_bytes)
    generated = root.attrib.get("date-generated") or root.attrib.get("dategenerated") or ""
    if not generated.startswith("09/19/2026"):
        raise ValueError(f"unexpected MedlinePlus generation date: {generated!r}")

    xml_hash = sha256_bytes(xml_bytes)
    found: dict[str, ET.Element] = {}
    for item in root.findall("health-topic"):
        topic_id = item.attrib.get("id", "")
        if topic_id in TOPICS and item.attrib.get("language") == "English":
            found[topic_id] = item
    missing = sorted(set(TOPICS) - set(found))
    if missing:
        raise ValueError(f"missing pinned MedlinePlus topics: {', '.join(missing)}")

    documents = []
    for topic_id, config in TOPICS.items():
        item = found[topic_id]
        summary = item.find("full-summary")
        if summary is None:
            raise ValueError(f"topic {topic_id} has no full-summary")
        body_text = summary_text(summary)
        if len(body_text) < 120:
            raise ValueError(f"topic {topic_id} summary is unexpectedly short")
        official_title = item.attrib.get("title", "").strip()
        created_at = item.attrib.get("date-created")
        if not created_at:
            raise ValueError(f"topic {topic_id} has no source creation date")
        source_created_at = datetime.strptime(created_at, "%m/%d/%Y").date()
        synonyms = [node.text.strip() for node in item.findall("also-called") if node.text and node.text.strip()]
        body = (
            f"# {config['title']}\n\n"
            f"中文检索词：{config['aliases']}\n\n"
            f"Official title: {official_title}\n\n"
            + (f"Also called: {', '.join(synonyms)}\n\n" if synonyms else "")
            # Keep retrieval labels and the evidence summary in one section.
            # A separate heading used to produce label-only top hits that gave
            # the answering model no actual medical source text.
            + "MedlinePlus summary:\n\n"
            + body_text
        )
        documents.append(MedicalDocument(
            doc_id=f"MPLUS-{topic_id}-{config['slug']}",
            version=1,
            title=config["title"],
            topic=config["topic"],
            audience="普通公众（官方英文资料）",
            source_org="MedlinePlus, U.S. National Library of Medicine",
            source_url=item.attrib["url"],
            source_published_at=source_created_at,
            status="source_checked",
            reviewer=SOURCE_CHECKER,
            reviewed_at=collected_at,
            next_review_at=collected_at + timedelta(days=30),
            license_note="MedlinePlus XML permits download and use with attribution to MedlinePlus.gov; retain source link.",
            source_sha256=xml_hash,
            source_locator=f"health-topic id={topic_id}; full-summary",
            source_collected_at=collected_at,
            source_version="MedlinePlus Health Topic XML 2026-09-19",
            usage_scope="Aide local research index; official English summary with Chinese retrieval labels",
            body=body,
        ))
    return documents


def import_archive(archive: Path, output: Path, collected_at: date | None = None) -> dict:
    assert_answer_eligible("medlineplus_topics")
    archive_bytes = archive.read_bytes()
    actual_hash = sha256_bytes(archive_bytes)
    if actual_hash != ARCHIVE_SHA256:
        raise ValueError(f"MedlinePlus archive hash changed: {actual_hash}")
    with zipfile.ZipFile(BytesIO(archive_bytes)) as bundle:
        names = [name for name in bundle.namelist() if name.lower().endswith(".xml")]
        if names != ["mplus_topics_2026-09-19.xml"]:
            raise ValueError(f"unexpected archive contents: {names}")
        xml_bytes = bundle.read(names[0])

    collected_at = collected_at or date.today()
    documents = build_documents(xml_bytes, collected_at)
    output.mkdir(parents=True, exist_ok=True)
    expected = set()
    for document in documents:
        path = output / f"{document.doc_id}.json"
        expected.add(path.name)
        path.write_text(json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for stale in output.glob("MPLUS-*.json"):
        if stale.name not in expected:
            stale.unlink()

    manifest = {
        "source": "MedlinePlus Health Topic XML",
        "download_url": SOURCE_DOWNLOAD_URL,
        "source_date": SOURCE_DATE.isoformat(),
        "archive_sha256": actual_hash,
        "xml_sha256": documents[0].source_sha256,
        "topic_ids": list(TOPICS),
        "documents": len(documents),
        "review_kind": "automated source parsing; no clinician review",
    }
    (output / "medlineplus_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Import pinned MedlinePlus topics")
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(import_archive(args.archive, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
