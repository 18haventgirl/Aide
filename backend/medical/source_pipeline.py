"""Build traceable research records from locally saved official source files.

This command never fetches arbitrary URLs and never changes publication status.
The input files are downloaded from the exact URLs in SOURCES.  The 66 clauses
from a government publication are matched against the national explanation PDF
before records receive ``source_checked``.  This is source checking, not a
clinical review or permission to publish the source text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from bisect import bisect_right
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from .schema import MedicalDocument


BASE = Path(__file__).resolve().parent
DOWNLOADS = BASE / "source_downloads"
OUTPUT = BASE / "source_corpus"
TODAY = date.today()
NEXT_REVIEW = date(TODAY.year + 1, TODAY.month, TODAY.day)
SOURCE_CHECKER = "Aide source pipeline (automated source comparison; non-clinician)"

SOURCES = {
    "notice": {
        "file": "health_literacy_2024_wnd.html",
        "url": "https://www.wnd.gov.cn/doc/2024/05/28/4333604.shtml",
        "org": "无锡市新吴区人民政府（转载国家卫生健康委正式通知）",
        "published": "2024-05-28",
    },
    "explanation": {
        "file": "health_literacy_2024_explanation.pdf",
        "url": "https://www.gov.cn/lianbo/bumen/202405/P020240530783730074981.pdf",
        "org": "国家卫生健康委员会（国务院网站托管正式释义）",
        "published": "2024-05-30",
    },
    "chest": {
        "file": "beijing_chest_pain_2022.html",
        "url": "https://wjw.beijing.gov.cn/bmfw_20143/jkzs/jzjj/202211/t20221102_2850165.html",
        "org": "北京市卫生健康委员会",
        "published": "2022-11-02",
    },
    "abdomen": {
        "file": "guangzhou_postmeal_abdominal_2026.html",
        "url": "https://kepu.wjw.gz.gov.cn/zs/content/post_5255.html",
        "org": "广州市卫生健康委员会健康科普平台",
        "published": "2026-02-24",
    },
}


class Paragraphs(HTMLParser):
    """Collect paragraph text, including text inside nested inline tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "p":
            if self.depth == 0:
                self.parts = []
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "p" and self.depth:
            self.depth -= 1
            if self.depth == 0:
                paragraph = re.sub(r"\s+", " ", "".join(self.parts)).strip()
                if paragraph:
                    self.paragraphs.append(paragraph)

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)


def paragraphs(html: str) -> list[str]:
    parser = Paragraphs()
    parser.feed(html)
    return parser.paragraphs


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(text: str) -> str:
    """Remove PDF line wraps, spacing and harmless punctuation variants."""
    return re.sub(r"[\s，,。．.；;：:（）()－—-]", "", text)


def notice_clauses(path: Path) -> list[str]:
    html = path.read_text(encoding="utf-8")
    if "国卫办宣传函〔2024〕191号" not in html or "（2024年版）" not in html:
        raise ValueError("not the final 2024 NHC notice")
    if "征求意见稿" in html:
        raise ValueError("consultation draft cannot enter the research corpus")
    numbered = []
    for p in paragraphs(html):
        match = re.match(r"^(\d{1,2})[.．]\s*(.+)$", p)
        if match:
            numbered.append((int(match.group(1)), match.group(2).strip()))
    for start in range(len(numbered)):
        run = numbered[start:start + 66]
        if [number for number, _ in run] == list(range(1, 67)):
            return [clause for _, clause in run]
    raise ValueError("official notice did not contain exactly ordered clauses 1-66")


def explanation_clauses(path: Path, notice: list[str]) -> list[tuple[str, int, int]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Install pypdf to inspect the official explanation PDF") from exc
    pdf = PdfReader(path)
    if len(pdf.pages) < 57:
        raise ValueError("explanation PDF is unexpectedly short")
    page_texts = [page.extract_text() or "" for page in pdf.pages]
    if "中国公民健康素养" not in page_texts[0] or "2024" not in page_texts[0]:
        raise ValueError("unexpected explanation PDF title or version")
    if "征求意见稿" in "".join(page_texts[:3]):
        raise ValueError("consultation draft cannot enter the research corpus")
    page_starts = []
    offset = 0
    for page_text in page_texts:
        page_starts.append(offset)
        offset += len(page_text) + 1
    full_text = "\n".join(page_texts)
    markers = list(re.finditer(r"(?m)^\s*(\d{1,2})[.．]\s*", full_text))
    selected = []
    after = 0
    for number, official_clause in enumerate(notice, 1):
        candidates = [match for match in markers if match.start() >= after and int(match.group(1)) == number]
        selected_match = None
        for match in candidates:
            probe = canonical(full_text[match.end():match.end() + len(official_clause) * 3])
            if probe.startswith(canonical(official_clause)):
                selected_match = match
                break
        if selected_match is None:
            raise ValueError(f"PDF clause {number} does not match final notice")
        selected.append(selected_match)
        after = selected_match.end()
    if len(selected) != 66:
        raise ValueError("not all 66 PDF clauses matched")

    references = full_text.find("参考文献", selected[-1].end())
    if references < 0:
        raise ValueError("cannot locate end of clause 66 before references")
    result = []
    for index, match in enumerate(selected):
        end = selected[index + 1].start() if index < 65 else references
        block = full_text[match.start():end]
        block = re.sub(r"(?m)^\s*\d{1,2}\s*$", "", block)
        block = re.sub(r"\n{3,}", "\n\n", block).strip()
        # PDF visual line wraps split Chinese words. Keep blank-line paragraph
        # boundaries while joining lines within each paragraph.
        block = "\n\n".join(part.replace("\n", "").strip() for part in block.split("\n\n"))
        start_page = bisect_right(page_starts, match.start())
        end_page = bisect_right(page_starts, end - 1)
        result.append((block, start_page, end_page))
    return result


def checked_record(**kwargs) -> dict:
    record = {
        "version": 1,
        "audience": "中国大陆中文成年人；本机研究版",
        "status": "source_checked",
        "reviewer": SOURCE_CHECKER,
        "reviewed_at": TODAY.isoformat(),
        "next_review_at": NEXT_REVIEW.isoformat(),
        "source_collected_at": TODAY.isoformat(),
        "source_version": "2024年正式版" if kwargs.get("topic") == "健康素养66条" else "原网页发布版",
        "withdrawn": False,
        "license_note": "仅本机研究和来源核对；公开展示或全文再分发前须核实原文使用条件并由医疗背景人员复核",
    }
    record.update(kwargs)
    return MedicalDocument.model_validate(record).model_dump(mode="json")


def source_manifest(paths: dict[str, Path], counts: dict) -> dict:
    return {
        "built_at": TODAY.isoformat(),
        "review_kind": "automated source comparison; no clinician review",
        "sources": [
            {"id": source_id, **info, "sha256": sha256(paths[source_id]), "bytes": paths[source_id].stat().st_size}
            for source_id, info in SOURCES.items()
        ],
        "checks": counts,
    }


def build(downloads: Path = DOWNLOADS, output: Path = OUTPUT) -> dict:
    paths = {name: downloads / info["file"] for name, info in SOURCES.items()}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing exact source files: " + ", ".join(missing))

    notice = notice_clauses(paths["notice"])
    explanation = explanation_clauses(paths["explanation"], notice)
    records: list[dict] = []
    pdf_hash = sha256(paths["explanation"])
    for number, (statement, (body, first, last)) in enumerate(zip(notice, explanation), 1):
        if not canonical(body).startswith(canonical(f"{number}.{statement}")):
            raise ValueError(f"explanation body {number} lost its official statement")
        records.append(checked_record(
            doc_id=f"NHC-HL2024-{number:02d}",
            title=f"健康素养第{number}条：{statement[:26].rstrip('，。；;,.')}",
            topic="健康素养66条",
            source_org=SOURCES["explanation"]["org"],
            source_url=SOURCES["explanation"]["url"],
            source_published_at=SOURCES["explanation"]["published"],
            source_sha256=pdf_hash,
            source_locator=f"第{number}条；PDF 第{first}" + (f"-{last}页" if last != first else "页"),
            usage_scope="健康科普；释义中的儿童、孕产妇等专门建议不用于成人个性化指导",
            body=f"# 健康素养第{number}条\n{body}",
        ))

    chest_html = paths["chest"].read_text(encoding="utf-8")
    if 'ArticleTitle" content="每周急救话题：胸痛的识别与处置"' not in chest_html:
        raise ValueError("unexpected Beijing chest-pain source")
    chest_paragraphs = paragraphs(chest_html)
    chest_text = [p for p in chest_paragraphs if p in {
        "询问患者胸痛的性质，如部位、范围、持续时间等，疼痛有无放射至肩部、面颊及下颌、颈部、背部、上肢或上腹部，是否有冠心病、糖尿病、高血压、高血脂等病史；发作前是否有劳累、激动、暴饮暴食、寒冷刺激、吸烟、大量饮酒等情况。",
        "观察患者是否有面色苍白、大汗淋漓、四肢湿冷、口唇青紫、呼吸困难及咯血等症状，并检查患者脉搏是否正常。",
        "当患者出现胸痛时，应立即拨打急救电话120，无论胸痛是否缓解，均需至医院就诊。",
    }]
    if len(chest_text) != 3:
        raise ValueError("Beijing chest-pain warning paragraphs changed")
    records.append(checked_record(
        doc_id="BJ-EMERG-CHEST-2022",
        title="胸痛时应如何求助与准备信息",
        topic="胸痛就医引导",
        source_org=SOURCES["chest"]["org"],
        source_url=SOURCES["chest"]["url"],
        source_published_at=SOURCES["chest"]["published"],
        source_sha256=sha256(paths["chest"]),
        source_locator="正文第1-3点（询问病情、观察症状、120急救）",
        usage_scope="北京市卫健委急救科普；成人突发胸痛求助，不能据此判断病因",
        body="# 胸痛就医引导\n" + "\n\n".join(chest_text),
    ))

    abdominal_html = paths["abdomen"].read_text(encoding="utf-8")
    if "春节聚餐后突发腹痛？这些情况要立即就医！" not in abdominal_html:
        raise ValueError("unexpected Guangzhou abdominal-pain source")
    abdominal_paragraphs = paragraphs(abdominal_html)
    warnings = [p for p in abdominal_paragraphs if "如果疼痛在短时间内持续加重" in p]
    if len(warnings) != 1 or "急诊科就诊" not in warnings[0]:
        raise ValueError("Guangzhou abdominal-pain warning changed")
    warning = warnings[0]
    # Keep only the exact warning sentence, excluding differential diagnoses and medication advice.
    warning = warning[warning.index("如果疼痛在短时间内持续加重"):]
    records.append(checked_record(
        doc_id="GZ-POSTMEAL-ABDOMEN-2026",
        title="聚餐后腹痛加重时的就医提示",
        topic="腹痛就医引导",
        source_org=SOURCES["abdomen"]["org"],
        source_url=SOURCES["abdomen"]["url"],
        source_published_at=SOURCES["abdomen"]["published"],
        source_sha256=sha256(paths["abdomen"]),
        source_locator="第二节：需要立即就医的危险信号",
        usage_scope="仅聚餐后突发腹痛场景；不泛化为所有腹痛，也不提供病因或用药判断",
        body="# 聚餐后腹痛的危险信号\n" + warning,
    ))

    output.mkdir(parents=True, exist_ok=True)
    for record in records:
        (output / f"{record['doc_id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    counts = {"final_notice_clauses": len(notice), "pdf_clauses_cross_checked": len(explanation),
              "symptom_records": 2, "records": len(records)}
    manifest = source_manifest(paths, counts)
    (output / "source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Build source-checked local research corpus")
    parser.add_argument("--downloads", type=Path, default=DOWNLOADS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.downloads, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
