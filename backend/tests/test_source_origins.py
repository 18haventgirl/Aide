"""Literal-source proof must not be supplied by an editor-created heading."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from medical.evidence_contract import build_evidence_pack
from medical.evaluation.metrics import score_ranges
from medical.source_origins import OriginResolver, validate_literal_references, verify_origin
from medical.source_provenance import body_hash
from medical.build_sleep_snapshot import RAW_ROOT, RAW_PATH
from tests.test_evidence_contract import document, hits_for


def fixture(root):
    raw = "原始标题\n明确结论。".encode()
    (root/"capture.txt").write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    doc = document(body="# 原始标题\n明确结论。\n# 编辑范围\n编辑注释").model_copy(update={"source_sha256": sha})
    parts = []
    for text, kind in (("原始标题", "source_heading"), ("明确结论。", "source_text"),
                       ("编辑范围", "editorial_heading"), ("编辑注释", "metadata")):
        start = doc.body.index(text)
        origin = raw.decode().find(text)
        parts.append({"body_range": [start, start+len(text)], "kind": kind,
                      "capture_range": [origin, origin+len(text)] if kind.startswith("source_") else None})
    for a in (0, doc.body.index("#", 1)):
        parts.append({"body_range": [a, a+2], "kind": "markup", "capture_range": None})
    manifest = {"schema_version": 1, "coordinate_unit": "unicode_codepoints", "doc_id": doc.doc_id,
                "document_version": doc.version, "body_sha256": body_hash(doc.body), "source_url": str(doc.source_url),
                "source_asset_sha256": sha, "capture": {"path": "capture.txt", "sha256": sha,
                "method": "synthetic_fixture_not_external_medical_data"}, "segments": parts}
    return doc, manifest


class OriginTests(unittest.TestCase):
    def test_editorial_heading_is_not_medical_evidence_and_gold_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); doc, manifest = fixture(root)
            resolver = OriginResolver([doc], {doc.doc_id: manifest}, root)
            pack = build_evidence_pack(hits_for(doc), resolver=resolver)
            def span(text):
                start = doc.body.index(text); return [start, start+len(text)]
            ref = {"doc_id": doc.doc_id, "version": doc.version, "body_sha256": body_hash(doc.body),
                   "ranges": [span("明确结论")], "required_conditions": [span("编辑范围")]}
            result = score_ranges(pack, [ref], resolver.documents)
            self.assertEqual(result["retained_spans"], 1)
            self.assertEqual(result["retained_conditions"], 0)
            cases = [{"id": "origin", "query": "合成问题", "expected_doc_ids": [doc.doc_id], "expected_evidence": [ref]}]
            with self.assertRaisesRegex(ValueError, "editorial/metadata"):
                validate_literal_references(cases, resolver)
            ref["required_conditions"] = [span("原始标题")]
            validate_literal_references(cases, resolver)
            from medical.diagnose_input_ranges import pool_pack
            hit = hits_for(doc)[0]
            pool, unknown = pool_pack([{"doc_id": doc.doc_id, "chunk_id": hit.chunk_id}], resolver)
            self.assertEqual(unknown, [])
            ref["required_conditions"] = [span("编辑范围")]
            self.assertEqual(score_ranges(pool, [ref], resolver.documents)["retained_conditions"], 0)

    def test_forged_offsets_overlap_unclassified_body_and_version_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); doc, manifest = fixture(root)
            bad = []
            value = copy.deepcopy(manifest); value["segments"][0]["capture_range"] = [0, 3]; bad.append(value)
            value = copy.deepcopy(manifest); value["segments"].append(value["segments"][0]); bad.append(value)
            value = copy.deepcopy(manifest); value["segments"].pop(); bad.append(value)
            value = copy.deepcopy(manifest); value["document_version"] = True; bad.append(value)
            value = copy.deepcopy(manifest); value["schema_version"] = True; bad.append(value)
            value = copy.deepcopy(manifest); value["segments"][2]["capture_range"] = [0, 4]; bad.append(value)
            for value in bad:
                with self.subTest(manifest=value), self.assertRaises(ValueError): verify_origin(doc, value, root)

    def test_changed_capture_and_path_traversal_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); doc, manifest = fixture(root)
            value = copy.deepcopy(manifest); value["capture"]["path"] = "../outside.txt"
            with self.assertRaisesRegex(ValueError, "approved raw root"): verify_origin(doc, value, root)
            (root/"capture.txt").write_text("不同的内容", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "capture hash"): verify_origin(doc, manifest, root)

    def test_absent_origin_never_silently_downgrades_to_canonical_only_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); doc, manifest = fixture(root)
            resolver = OriginResolver([doc], {}, root)
            hit = hits_for(doc)[0]
            self.assertEqual(resolver.resolve(hit, hit.text)["status"], "unmapped")
            self.assertEqual(resolver.resolve(hit, hit.text)["reason"], "missing_source_origin_manifest")

    @unittest.skipUnless((RAW_ROOT/RAW_PATH).is_file(), "local official-source capture not installed")
    def test_real_adult_sleep_capture_is_exact_and_keeps_variation(self):
        from medical.build_sleep_snapshot import RAW_ROOT, build_document
        doc, manifest = build_document()
        self.assertNotIn("6岁以下", doc.body)
        self.assertNotIn("0-3月龄", doc.body)
        self.assertIn("因人而异", doc.body)
        self.assertIn("成年人7-8小时", doc.body)
        self.assertNotIn("中药汤剂", doc.body)
        verified = verify_origin(doc, manifest, RAW_ROOT)
        self.assertEqual({p["kind"] for p in verified["segments"]}, {"source_text", "source_heading", "markup"})

    def test_editorial_document_requires_exact_unique_source_payload(self):
        from medical.capture_existing_origins import map_editorial_document
        doc = document(body="# 编辑标题\n明确结论。")
        capture = {"path": "capture.txt", "sha256": "a"*64, "method": "fixture"}
        origin = map_editorial_document(doc, "明确结论。", "原始上下文。明确结论。", capture)
        self.assertEqual(origin["segments"][-1]["capture_range"], [6, 11])
        self.assertEqual(origin["segments"][1]["kind"], "editorial_heading")
        for payload, text in (("不同的结论。", "不同的结论。"), ("明确结论。", "明确结论。明确结论。")):
            with self.subTest(payload=payload, text=text), self.assertRaises(ValueError):
                map_editorial_document(doc, payload, text, capture)

    def test_noncontiguous_paragraphs_keep_order_and_skip_other_source_content(self):
        from medical.capture_existing_origins import map_editorial_document
        doc = document(body="# 编辑标题\n第一段。\n\n第三段。")
        capture = {"path": "capture.txt", "sha256": "a"*64, "method": "fixture"}
        origin = map_editorial_document(doc, "第一段。\n\n第三段。", "第一段。\n\n中间未选入。\n\n第三段。", capture,
                                        paragraph_selection=True)
        self.assertEqual(len(origin["segments"]), 4)
        self.assertLess(origin["segments"][-2]["capture_range"][1], origin["segments"][-1]["capture_range"][0])
        with self.assertRaisesRegex(ValueError, "ordered"):
            map_editorial_document(doc, "第一段。\n\n第三段。", "第三段。\n\n第一段。", capture, paragraph_selection=True)

    def test_derived_capture_is_idempotent_and_refuses_different_content(self):
        from medical.capture_existing_origins import _save_capture
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = _save_capture(root, Path("source/derived.txt"), "已保存的文字。\n")
            self.assertEqual(first, _save_capture(root, Path("source/derived.txt"), "已保存的文字。\n"))
            with self.assertRaisesRegex(ValueError, "never replace"):
                _save_capture(root, Path("source/derived.txt"), "不同文字。\n")
            with self.assertRaisesRegex(ValueError, "raw root"):
                _save_capture(root, Path("../outside.txt"), "不能写入。")

    def test_changed_original_asset_fails_before_extraction(self):
        from medical.capture_existing_origins import reconstruct
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"notice.html").write_text("changed", encoding="utf-8")
            (root/"manifest.json").write_text(json.dumps({"sources": [{"id": "notice", "file": "notice.html", "sha256": "0"*64}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pinned source asset changed"):
                reconstruct([], root/"raw", downloads=root, source_manifest=root/"manifest.json")

    def test_section_correction_versions_only_the_new_document(self):
        from medical.capture_existing_origins import map_editorial_document, narrow_abdominal_excerpt
        from medical.schema import MedicalDocument
        from medical.experiment import MEDICAL
        data = json.loads((MEDICAL/"source_corpus/GZ-POSTMEAL-ABDOMEN-2026.json").read_text(encoding="utf-8"))
        doc = MedicalDocument.model_validate(data)
        before = doc.model_dump(mode="json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = doc.body.partition("\n")[2]
            (root/"capture.txt").write_bytes(payload.encode())
            capture = {"path": "capture.txt", "sha256": hashlib.sha256(payload.encode()).hexdigest(), "method": "fixture"}
            manifest = map_editorial_document(doc, payload, payload, capture)
            updated, origin = narrow_abdominal_excerpt(doc, manifest, root)
            self.assertEqual(updated.version, 2)
            self.assertNotIn("三、高危人群", updated.body)
            self.assertTrue(updated.body.endswith("以免掩盖病情、延误诊治。"))
            self.assertEqual(doc.model_dump(mode="json"), before)
            self.assertEqual(origin["previous_snapshot"]["body_sha256"], body_hash(doc.body))
            self.assertTrue(origin["omissions"][0]["capture_range"][0] < origin["omissions"][0]["capture_range"][1])


if __name__ == "__main__": unittest.main()
