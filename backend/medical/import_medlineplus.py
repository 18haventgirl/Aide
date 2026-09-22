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
from datetime import date, timedelta
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

from .schema import MedicalDocument


BASE = Path(__file__).resolve().parent
DEFAULT_ARCHIVE = BASE / "source_downloads" / "mplus_topics_compressed_2026-09-19.zip"
DEFAULT_OUTPUT = BASE / "source_corpus"
ARCHIVE_SHA256 = "4b52e1a2c4c499d363dfbff1776875b53a695b315e7761e1c283b223b675ed74"
SOURCE_DATE = date(2026, 9, 19)
SOURCE_DOWNLOAD_URL = "https://medlineplus.gov/xml/mplus_topics_compressed_2026-09-19.zip"
SOURCE_CHECKER = "Aide MedlinePlus importer (automated source parsing; non-clinician)"

# A deliberately small first batch. Chinese terms are retrieval labels rather
# than translations of the evidence body.
TOPICS = {
    "3061": {"slug": "abdominal-pain", "title": "腹痛（Abdominal Pain）", "topic": "腹痛", "aliases": "肚子痛、肚子疼、腹部疼痛、胃疼"},
    "196": {"slug": "common-cold", "title": "普通感冒（Common Cold）", "topic": "普通感冒", "aliases": "感冒、鼻塞、流鼻涕"},
    "1543": {"slug": "cough", "title": "咳嗽（Cough）", "topic": "咳嗽", "aliases": "咳嗽、干咳、咳痰"},
    "211": {"slug": "diarrhea", "title": "腹泻（Diarrhea）", "topic": "腹泻", "aliases": "拉肚子、稀便、水样便"},
    "511": {"slug": "fever", "title": "发热（Fever）", "topic": "发热", "aliases": "发烧、体温升高、低烧、高烧"},
    "273": {"slug": "headache", "title": "头痛（Headache）", "topic": "头痛", "aliases": "头疼、头部疼痛、偏头痛"},
    "489": {"slug": "nausea-vomiting", "title": "恶心与呕吐（Nausea and Vomiting）", "topic": "恶心呕吐", "aliases": "恶心、想吐、呕吐、吐了"},
    "4748": {"slug": "sore-throat", "title": "咽痛（Sore Throat）", "topic": "咽痛", "aliases": "嗓子疼、喉咙痛、咽喉疼痛"},
}


class SummaryText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "li":
            self.parts.append("\n- ")
        elif tag.lower() in {"p", "br", "h1", "h2", "h3", "ul", "ol"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "li", "ul", "ol"}:
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
        synonyms = [node.text.strip() for node in item.findall("also-called") if node.text and node.text.strip()]
        body = (
            f"# {config['title']}\n\n"
            f"中文检索词：{config['aliases']}\n\n"
            f"Official title: {official_title}\n\n"
            + (f"Also called: {', '.join(synonyms)}\n\n" if synonyms else "")
            + "## MedlinePlus summary\n\n"
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
            source_published_at=SOURCE_DATE,
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
