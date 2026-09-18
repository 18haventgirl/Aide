"""Import the NHC 2024 health-literacy source as reviewable draft records.

The importer does not publish or index its output. A human reviewer must check
the extracted clauses, usage rights, audience, and dates before publication.
"""

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen


SOURCE_URL = "https://www.nhc.gov.cn/xcs/c100123/202405/73a4927142f34152abed875634a3c13b.shtml"


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored += 1
        elif tag in {"p", "div", "br", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.ignored -= 1
        elif tag in {"p", "div", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def parse_clauses(html: str) -> list[str]:
    parser = TextExtractor()
    parser.feed(html)
    text = re.sub(r"[\u00a0\u3000\t]+", " ", "".join(parser.parts))
    text = re.sub(r"\n\s*\n+", "\n", text)
    matches = list(re.finditer(r"(?m)^\s*(\d{1,2})[.．、]\s*", text))
    for start in range(len(matches)):
        if matches[start].group(1) != "1":
            continue
        run = matches[start:start + 66]
        if len(run) != 66 or [int(item.group(1)) for item in run] != list(range(1, 67)):
            continue
        clauses = []
        for offset, match in enumerate(run):
            end = run[offset + 1].start() if offset < 65 else len(text)
            clause = re.sub(r"\s+", " ", text[match.end():end]).strip()
            if offset == 65:
                clause = clause.split("相关链接", 1)[0].strip()
            if not clause:
                raise ValueError(f"empty source clause {offset + 1}")
            clauses.append(clause)
        return clauses
    raise ValueError("could not identify all 66 numbered clauses in official source")


def main():
    parser = argparse.ArgumentParser(description="Fetch official NHC text into draft review records")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("source_drafts"))
    parser.add_argument("--html", type=Path, help="read a previously downloaded official HTML file")
    args = parser.parse_args()
    if args.html:
        html = args.html.read_text(encoding="utf-8")
    else:
        request = Request(SOURCE_URL, headers={"User-Agent": "AideMedicalKnowledgeBuilder/1.0"})
        with urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="replace")
    clauses = parse_clauses(html)
    args.output.mkdir(parents=True, exist_ok=True)
    for number, clause in enumerate(clauses, 1):
        record = {
            "doc_id": f"NHC-HL2024-{number:02d}", "version": 1,
            "title": clause[:32].rstrip("，。；;,."),
            "topic": "中国公民健康素养（2024年版）",
            "audience": "普通公众", "source_org": "国家卫生健康委员会",
            "source_url": SOURCE_URL, "source_published_at": "2024-05-30",
            "status": "draft", "reviewer": None, "reviewed_at": None,
            "next_review_at": None,
            "license_note": "官方原文摘录；发布前核实转载条件和医疗内容",
            "body": f"# 第{number}条\n{clause}",
        }
        path = args.output / f"{record['doc_id']}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"draft_records": len(clauses), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
