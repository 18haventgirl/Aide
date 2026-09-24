"""Versioned, streaming Huatuo-Lite research preparation; never publishes evidence.

Run download, prepare, then index with explicit resource gates. Corpus and indexes
live under a dataset/revision directory; only code and manifests belong in Git.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import time
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "medical-rag-data/registry/huatuo_lite.lock.json"
DEFAULT_ROOT = ROOT / "medical-rag-data/datasets"
POLICY_VERSION = "adult-general-screen-v1"


def lock() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def directory(root: Path = DEFAULT_ROOT) -> Path:
    return root / "huatuo26m-lite" / ("hf-" + lock()["revision"][:12])


def filename(stage: str, suffix: str) -> str:
    return f"huatuo26m-lite__{lock()['revision'][:12]}__{stage}.{suffix}"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def download(root: Path = DEFAULT_ROOT, endpoint: str = "https://huggingface.co",
             proxy: str | None = None) -> Path:
    import requests
    if endpoint not in {"https://huggingface.co", "https://hf-mirror.com", "https://modelscope.cn"}:
        raise ValueError("unsupported download endpoint")
    pinned = lock()
    target = directory(root) / "raw" / filename("raw", "jsonl")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size == pinned["bytes"] and digest(target) == pinned["sha256"]:
            return target
        raise ValueError("existing raw data failed checksum; inspect before replacing")
    if shutil.disk_usage(target.parent).free < pinned["bytes"] + 512 * 1024**2:
        raise RuntimeError("insufficient free disk for download and pilot")
    temporary = target.with_suffix(".jsonl.part")
    offset = temporary.stat().st_size if temporary.exists() else 0
    url = f"{endpoint}/datasets/{pinned['repository']}/resolve/{pinned['revision']}/{pinned['filename']}"
    if endpoint == "https://modelscope.cn":
        url = (f"{endpoint}/api/v1/datasets/{pinned['repository']}/repo?"
               f"Revision={pinned['modelscope_revision']}&FilePath={pinned['filename']}")
    session = requests.Session()
    if proxy:
        session.trust_env = False
        session.proxies = {"http": proxy, "https": proxy}
    headers = {"User-Agent": "Aide-local-dataset-research/1.0", "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    if offset != pinned["bytes"]:
        with session.get(url, headers=headers, stream=True, timeout=(15, 40)) as response:
            response.raise_for_status()
            if response.status_code == 206:
                if not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise ValueError("unexpected partial response range")
                mode = "ab"
            else:
                mode, offset = "wb", 0
            last_log = time.monotonic()
            with temporary.open(mode) as output:
                for block in response.iter_content(256 * 1024):
                    if not block:
                        continue
                    offset += len(block)
                    if offset > pinned["bytes"]:
                        raise ValueError("download exceeds pinned size")
                    output.write(block)
                    if time.monotonic() - last_log > 10:
                        print(f"downloaded {offset}/{pinned['bytes']} bytes", flush=True)
                        last_log = time.monotonic()
    if temporary.stat().st_size != pinned["bytes"] or digest(temporary) != pinned["sha256"]:
        raise ValueError("download failed pinned size/SHA256 validation")
    temporary.replace(target)
    write_report(target.parent / "download_manifest.json", {
        **pinned, "download_url": url, "raw_file": target.name,
        "downloaded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    return target


# These are exclusion heuristics for a small adult/general pilot, not a medical
# quality classifier. Even records passing all rules remain unverified candidates.
RULES = {
    "outside_adult_scope": r"婴|幼儿|宝宝|孩子|儿童|小孩|新生儿|儿子|女儿|怀孕|孕妇|妊娠|哺乳|产后|人流",
    "specialist_or_emergency": r"癌|肿瘤|化疗|放疗|癫痫|自杀|昏迷|呕血|心肌梗|脑梗|卒中|呼吸困难|胸痛",
    "drug_or_procedure": r"服用|口服|注射|输液|抗生素|抗菌药|激素|手术|处方|用药|药物|药品|剂量|毫克|\bmg\b|布洛芬|阿莫西林",
    "unsupported_claim": r"根治|包治|偏方|排毒|清除.{0,6}垃圾|软化血管|补肾|壮阳|气血|经络|穴位|中药|中医|酒精|白酒|安痛定",
    "privacy_or_promotion": r"https?://|www\.|1[3-9]\d{9}|微信|加群|QQ|哪家医院|多少钱|推荐.{0,5}医院",
    "instruction_injection": r"忽略.{0,12}指令|系统提示|system\s*:|assistant\s*:|ignore.{0,12}instructions",
}
COMPILED_RULES = {name: re.compile(value, re.I) for name, value in RULES.items()}
TOPICS = {
    "sleep": r"睡眠|失眠|熬夜",
    "activity": r"运动|锻炼|跑步|久坐",
    "nutrition": r"饮食|营养|饮水|喝水|蔬菜|水果|食物|饮食习惯",
    "prevention": r"预防|戒烟|吸烟|饮酒|洗手|卫生",
    "common_symptoms": r"感冒|咳嗽|咽|嗓子|头痛|腹泻|便秘|腹痛|发烧|发热",
}


def screen(row: dict) -> tuple[dict | None, list[str]]:
    if not isinstance(row, dict) or not isinstance(row.get("question"), str) or not isinstance(row.get("answer"), str):
        return None, ["invalid_schema"]
    q, a = row["question"].strip(), row["answer"].strip()
    text = q + "\n" + a
    reasons = []
    if not (8 <= len(q) <= 220 and 30 <= len(a) and len(text) <= 450):
        reasons.append("length_outside_pilot_bounds")
    if any(len(re.findall(r"[\u4e00-\u9fff]", part)) / max(1, len(part)) < 0.55 for part in (q, a)):
        reasons.append("not_chinese_body")
    if not isinstance(row.get("id"), int) or isinstance(row.get("id"), bool):
        reasons.append("invalid_id")
    reasons.extend(name for name, pattern in COMPILED_RULES.items() if pattern.search(text))
    if row.get("label") in {"儿科", "妇产科", "生殖健康科", "肿瘤科", "中医科"}:
        reasons.append("outside_pilot_department")
    # Generic diet/rest advice in an answer must not make an unrelated disease
    # question look like a nutrition/sleep question.
    topics = [topic for topic, pattern in TOPICS.items() if re.search(pattern, q)]
    if not topics:
        reasons.append("outside_pilot_topics")
    if reasons:
        return None, reasons
    normalized_question = re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", q)).lower()
    return {
        "id": f"HTL-{row['id']}", "source_record_id": row["id"], "question": q, "answer": a,
        "department": row.get("label", ""), "related_diseases": row.get("related_diseases", ""),
        "dataset_score": row.get("score"), "topics": topics, "language": "zh",
        "question_sha256": hashlib.sha256(normalized_question.encode()).hexdigest(),
        "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "review_status": "heuristic_screened_unverified", "answer_eligible": False,
        "source_type": "community_qa_model_rewritten", "original_medical_source_url": None,
    }, []


def prepare(root: Path = DEFAULT_ROOT, limit: int = 5000) -> dict:
    if not 1 <= limit <= 10000:
        raise ValueError("pilot limit must be 1..10000")
    pinned = lock()
    base = directory(root)
    raw = base / "raw" / filename("raw", "jsonl")
    if raw.stat().st_size != pinned["bytes"] or digest(raw) != pinned["sha256"]:
        raise ValueError("raw corpus failed pinned size/SHA256 validation")
    target = base / "screened" / filename(POLICY_VERSION, "sqlite")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".sqlite.part")
    if temporary.exists():
        temporary.unlink()
    started = time.perf_counter()
    counts, rejected, departments, topics = Counter(), Counter(), Counter(), Counter()
    with closing(sqlite3.connect(temporary)) as db:
        db.execute("PRAGMA cache_size=-4096")
        db.execute("PRAGMA temp_store=FILE")
        db.executescript("""
            CREATE TABLE candidates(id TEXT PRIMARY KEY, question_hash TEXT UNIQUE NOT NULL,
              content_hash TEXT NOT NULL, sample_key TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE audit(line INTEGER PRIMARY KEY, record_id TEXT, reasons TEXT NOT NULL);
        """)
        with raw.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                counts["raw_rows"] += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    row = None
                candidate, reasons = screen(row)
                if candidate:
                    candidate.update({
                        "source_revision": pinned["revision"], "source_line": line_number,
                        "dataset_url": f"https://huggingface.co/datasets/{pinned['repository']}/tree/{pinned['revision']}",
                        "license_declared": pinned["license_declared"], "screen_policy": POLICY_VERSION,
                    })
                    sample_key = hashlib.sha256(("aide-pilot-v1:" + candidate["id"]).encode()).hexdigest()
                    try:
                        db.execute("INSERT INTO candidates VALUES (?,?,?,?,?)", (
                            candidate["id"], candidate["question_sha256"], candidate["content_sha256"],
                            sample_key, json.dumps(candidate, ensure_ascii=False)))
                        counts["screen_passed_unverified"] += 1
                    except sqlite3.IntegrityError:
                        reasons = ["duplicate_id_or_question"]
                if reasons:
                    counts["rejected_rows"] += 1
                    rejected.update(reasons)
                    source_id = str(row.get("id", "")) if isinstance(row, dict) else ""
                    db.execute("INSERT INTO audit VALUES (?,?,?)", (line_number, source_id, json.dumps(reasons)))
                if line_number % 10000 == 0:
                    db.commit()
                    print(f"screened {line_number} rows", flush=True)
        db.execute("CREATE INDEX candidate_sample_order ON candidates(sample_key)")
        db.commit()
        output = base / "normalized" / filename(f"pilot-{limit}-{POLICY_VERSION}", "jsonl")
        output.parent.mkdir(parents=True, exist_ok=True)
        output_part = output.with_suffix(".jsonl.part")
        with output_part.open("w", encoding="utf-8", newline="\n") as destination:
            for (payload,) in db.execute("SELECT payload FROM candidates ORDER BY sample_key LIMIT ?", (limit,)):
                destination.write(payload + "\n")
                record = json.loads(payload)
                departments[record["department"]] += 1
                topics.update(record["topics"])
                counts["selected_rows"] += 1
        output_part.replace(output)
    temporary.replace(target)
    report = {
        "dataset_id": pinned["dataset_id"], "revision": pinned["revision"], "raw_sha256": pinned["sha256"],
        "policy": POLICY_VERSION, "requested_limit": limit, **counts,
        "rejection_reason_counts": dict(rejected), "selected_departments": dict(departments),
        "selected_topics": dict(topics), "sample_file": str(output.relative_to(base)),
        "sample_sha256": digest(output), "screen_database": str(target.relative_to(base)),
        "elapsed_seconds": round(time.perf_counter() - started, 2), "answer_eligible": False,
        "clinical_validation": "not_performed", "original_medical_sources_available": False,
        "sampling": "deterministic SHA256 ordering after exact-question deduplication; not a representative clinical sample",
    }
    from .resource_budget import memory_status
    report["memory"] = memory_status()
    write_report(base / "reports" / filename(f"pilot-{limit}-{POLICY_VERSION}", "json"), report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["download", "prepare"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--endpoint", default="https://huggingface.co")
    parser.add_argument("--proxy")
    args = parser.parse_args()
    if args.command == "download":
        print(download(args.root, args.endpoint, args.proxy))
    else:
        print(json.dumps(prepare(args.root, args.limit), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
