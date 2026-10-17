"""Build an isolated adult Chinese source snapshot from a verified DOM capture.

Historical corpus files remain untouched. In this new snapshot the abdominal
excerpt is versioned to correct a section boundary. No serving index or user DB
is opened. Source headings are distinguished from generated Markdown.
"""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path

from .experiment import MEDICAL, ROOT, digest, repository_version
from .knowledge_base import load_corpus
from .schema import MedicalDocument
from .source_origins import verify_origin
from .source_provenance import body_hash
from .capture_existing_origins import reconstruct, narrow_abdominal_excerpt


URL = "https://www.nhc.gov.cn/guihuaxxs/c100133/202503/70d5836afe804a858b899ee951a24a13.shtml"
RAW_ROOT = ROOT/"medical-rag-data/raw"
RAW_PATH = Path("nhc-sleep-core-20250318/2026-10-17/article-rendered.txt")
RAW_SHA = "6626dab162e77f0145225fda8d3b14595db04a4bdc792b565d34196470086925"
CAPTURE_SHA = "c7bc722103b6313e54900b5a5ca9b2d86348abf3b9987a22e75fefb037e1e93c"


def build_document(raw_root=RAW_ROOT):
    raw = (raw_root/RAW_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != RAW_SHA:
        raise ValueError("sleep capture differs; create a new reviewed capture version")
    source = raw.decode("utf-8")
    article = source.rstrip("\n")
    if hashlib.sha256(article.encode()).hexdigest() != CAPTURE_SHA:
        raise ValueError("rendered article content differs")
    paragraphs = article.split("\n\n")
    if len(paragraphs) != 24: raise ValueError("unexpected official article structure")
    offsets, at = [], 0
    for paragraph in paragraphs:
        offsets.append(at); at += len(paragraph)+2
    body, parts = "", []
    def generated(text):
        nonlocal body
        if text:
            a = len(body); body += text
            parts.append({"body_range": [a, len(body)], "kind": "markup", "capture_range": None})
    def copied(index, a=0, b=None, kind="source_text"):
        nonlocal body
        text = paragraphs[index]
        b = len(text) if b is None else b
        if a < b:
            start = len(body); body += text[a:b]
            parts.append({"body_range": [start, len(body)], "kind": kind,
                          "capture_range": [offsets[index]+a, offsets[index]+b], "paragraph_index": index})
    selected = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 15, 16, 17, 18, 19, 20, 21, 22, 23]
    headings = {0, 2, 6, 9, 17, 20, 22}
    omitted = []
    for index in selected:
        if body: generated("\n\n")
        if index in headings:
            generated("# "); copied(index, kind="source_heading"); continue
        text = paragraphs[index]
        if index == 3:
            end = text.index("一般来说，")+len("一般来说，")
            adult = text.index("成年人7-8小时")
            copied(index, 0, end); copied(index, adult)
            omitted.append({"paragraph_index": index, "capture_range": [offsets[index]+end, offsets[index]+adult],
                            "reason": "pediatric_subgroup_excluded_from_adult_subset"})
        elif index in {4, 21}:
            exclusion = "（6岁以下儿童在20分钟以内）" if index == 4 else "，6岁以下超过20分钟"
            left = text.index(exclusion); right = left+len(exclusion)
            copied(index, 0, left); copied(index, right)
            omitted.append({"paragraph_index": index, "capture_range": [offsets[index]+left, offsets[index]+right],
                            "reason": "pediatric_exception_excluded_adult_scope_only"})
        elif index == 23:
            end = text.index("需采用不同的治疗手段。")+len("需采用不同的治疗手段。")
            copied(index, 0, end)
            omitted.append({"paragraph_index": index, "capture_range": [offsets[index]+end, offsets[index]+len(text)],
                            "reason": "treatment_modalities_not_selected_for_general_guidance"})
        else:
            copied(index)
    document = MedicalDocument(doc_id="NHC-SLEEP-CORE-20250318", version=1,
        title="成人睡眠健康：个体差异、生活习惯与寻求帮助", topic="成人睡眠健康科普", audience="中文成年人；仅本机研究",
        source_org="国家卫生健康委员会（全国爱卫办）", source_url=URL, source_published_at=date(2025, 3, 18),
        status="source_checked", reviewer="Aide DOM capture and exact-range verification (non-clinician)",
        reviewed_at=date(2026, 10, 17), next_review_at=date(2027, 4, 17), source_collected_at=date(2026, 10, 17),
        source_sha256=RAW_SHA, source_version="2025-03-18 public article; browser-rendered paragraph snapshot, not HTTP HTML",
        source_locator="全国爱卫办睡眠核心信息；DOM段落0-23中的成人适用子集；逐段范围见origin sidecar",
        license_note="官方公开页面；仅本机研究与来源核对，未据此确认全文再分发/公开应用许可。",
        usage_scope="仅成人一般睡眠科普与求助信息；保留个体差异，不以单项时长或打鼾自行诊断；儿童段落/例外与治疗方法列表未选入。",
        body=body)
    origin = {"schema_version": 1, "coordinate_unit": "unicode_codepoints", "doc_id": document.doc_id,
        "document_version": document.version, "body_sha256": body_hash(body), "source_url": URL,
        "source_asset_sha256": RAW_SHA, "capture": {"path": RAW_PATH.as_posix(), "sha256": RAW_SHA,
            "method": "browser_dom_paragraph_text", "format": "browser_rendered_text_not_http_html",
            "article_text_sha256_without_final_newline": CAPTURE_SHA, "browser_utf16_length": 2835,
            "browser_rolling32": 751566240, "collected_client_date": "2026-10-17"},
        "segments": parts, "omissions": omitted,
        "omitted_full_paragraphs": [12, 13, 14], "public_answer_eligible": False}
    verify_origin(document, origin, raw_root)
    return document, origin


def build_snapshot(output):
    output = output.resolve()
    allowed = (ROOT/"medical-rag-data/datasets").resolve()
    if not output.is_relative_to(allowed): raise ValueError("snapshot must stay inside the approved datasets root")
    if output.exists(): raise FileExistsError("never overwrite a corpus snapshot")
    documents = load_corpus(MEDICAL/"source_corpus")
    document, origin = build_document()
    if document.doc_id in {d.doc_id for d in documents}: raise ValueError("duplicate new source ID")
    mappings = reconstruct(documents, RAW_ROOT)
    original = next(d for d in documents if d.doc_id == "GZ-POSTMEAL-ABDOMEN-2026")
    corrected, corrected_origin = narrow_abdominal_excerpt(original, mappings[original.doc_id], RAW_ROOT)
    mappings[corrected.doc_id] = corrected_origin
    mappings[document.doc_id] = origin
    output.mkdir(parents=True)
    corpus, origins = output/"corpus", output/"origins"
    corpus.mkdir(); origins.mkdir()
    state = {"complete": False, "code": repository_version(), "scope": "isolated_local_research_not_active_index",
             "baseline_corpus_sha256": digest([d.model_dump(mode="json") for d in documents])}
    target = output/"snapshot_manifest.json"
    target.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    for path in (MEDICAL/"source_corpus").glob("*.json"):
        if path.name.endswith("_manifest.json"): continue
        (corpus/path.name).write_bytes(path.read_bytes())
    (corpus/f"{document.doc_id}.json").write_text(document.model_dump_json(indent=2)+"\n", encoding="utf-8")
    (corpus/f"{corrected.doc_id}.json").write_text(corrected.model_dump_json(indent=2)+"\n", encoding="utf-8")
    for doc_id, value in mappings.items():
        (origins/f"{doc_id}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    merged = load_corpus(corpus)
    for doc in merged:
        if doc.doc_id in mappings: verify_origin(doc, mappings[doc.doc_id], RAW_ROOT)
    state.update(complete=True, documents=len(merged), added_documents=1,
                 corpus_sha256=digest([d.model_dump(mode="json") for d in merged]),
                 added_doc_id=document.doc_id, origin_verified_documents=len(mappings),
                 origins_sha256=digest(mappings),
                 origin_manifests_pending=sorted(d.doc_id for d in merged if d.doc_id not in mappings),
                 changed_documents=[{"doc_id": corrected.doc_id, "from_version": original.version,
                    "to_version": corrected.version, "old_body_sha256": body_hash(original.body),
                    "new_body_sha256": body_hash(corrected.body),
                    "reason": "remove_following_section_outside_declared_abdominal_excerpt"}])
    target.write_text(json.dumps(state, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_snapshot(args.output), ensure_ascii=False))
