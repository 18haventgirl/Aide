"""Recovery must separate the original excerpt, new transcript, and source offsets."""
import json
from pathlib import Path
import tempfile
import unittest

from medical.capture_legacy_symptoms import RAW, RECIPE, build_record, render_excerpt
from medical.experiment import MEDICAL, digest
from medical.knowledge_base import load_corpus
from medical.schema import MedicalDocument
from medical.source_origins import verify_origin
from medical.source_provenance import body_hash
from tests.test_evidence_contract import document


def fixture(root):
    previous = document(body="# 编辑小节\n一句。另一局。")
    previous = previous.model_copy(update={"source_sha256": body_hash(previous.body)})
    html = "<p>署名：一句。</p><p>另一句。感谢。</p>"
    (root / "page.html").write_bytes(html.encode())
    spec = {"doc_id": previous.doc_id, "previous_document_sha256": digest(previous.model_dump(mode="json")),
            "kind": "official_parallel_transcript", "source_url": "https://example.org/new",
            "source_org": "合成来源", "source_published_at": "2024-01-01", "source_locator": "合成段落",
            "html_path": "page.html", "html_sha256": body_hash(html), "paragraph_count": 2,
            "capture_sha256": body_hash("署名：一句。\n\n另一句。感谢。\n"), "sections": [[[0, 3, 6], [1, 0, 4]]],
            "body_sha256": body_hash("# 编辑小节\n一句。另一句。"), "reason": "合成历史错字"}
    return previous, spec


class LegacyOriginTests(unittest.TestCase):
    def test_parallel_transcript_keeps_two_coordinates_and_credits_actual_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, spec = fixture(root)
            before = old.model_dump(mode="json")
            mode, bundle = build_record(old, spec, "2026-11-02", root)
            self.assertEqual(mode, "bundle")
            doc = MedicalDocument.model_validate(bundle["document"])
            origin = bundle["origin"]
            checked = verify_origin(doc, origin, root)
            self.assertEqual(doc.version, old.version + 1)
            self.assertEqual(str(doc.source_url), spec["source_url"])
            self.assertEqual(doc.source_sha256, spec["html_sha256"])
            self.assertEqual(origin["previous_snapshot"]["source_url"], str(old.source_url))
            self.assertEqual(old.model_dump(mode="json"), before)
            parts = [p for p in checked["segments"] if p["kind"] == "source_text"]
            self.assertEqual(len(parts), 2)
            self.assertEqual(parts[0]["body_range"][1], parts[1]["body_range"][0])
            self.assertEqual(parts[1]["capture_range"][0] - parts[0]["capture_range"][1], 2)
            self.assertEqual(checked["segments"][1]["kind"], "editorial_heading")

    def test_page_or_selection_changes_cannot_preserve_the_old_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, spec = fixture(root)
            with self.assertRaisesRegex(ValueError, "origin-only"):
                build_record(old, {**spec, "kind": "same_original_page"}, "2026-11-02", root)
            for field, value, message in (("previous_document_sha256", "0"*64, "previous document"),
                                          ("body_sha256", "0"*64, "selected body"),
                                          ("capture_sha256", "0"*64, "pinned derived"),
                                          ("html_sha256", "0"*64, "pinned HTML"),
                                          ("html_path", "../escape.html", "approved root")):
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                    build_record(old, {**spec, field: value}, "2026-11-02", root)
            self.assertFalse((root/"extracted-paragraphs.txt").exists())

    def test_bounds_order_and_boolean_coordinates_are_rejected(self):
        old = document(body="# 编辑标题\n句子")
        for spans in ([[[0, 0, 2], [0, 1, 3]]], [[[1, 0, 1]]], [[[0, True, 2]]], [[[0, -1, 1]]]):
            with self.subTest(spans=spans), self.assertRaises(ValueError):
                render_excerpt(old, spans, ["三个字"])

    def test_installed_official_assets_replay_all_three_versions(self):
        recipe = json.loads(RECIPE.read_bytes())
        if not all((RAW / s["html_path"]).is_file() for s in recipe["sources"]):
            self.skipTest("requires fixed local Chinese HTML assets")
        by_id = {d.doc_id: d for d in load_corpus(MEDICAL / "source_corpus")}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = {}
            for spec in recipe["sources"]:
                asset = root / spec["html_path"]
                asset.parent.mkdir(parents=True, exist_ok=True)
                asset.write_bytes((RAW / spec["html_path"]).read_bytes())
                old = by_id[spec["doc_id"]]
                mode, payload = build_record(old, spec, recipe["collected_at"], root)
                doc = MedicalDocument.model_validate(payload["document"]) if mode == "bundle" else old
                origin = payload["origin"] if mode == "bundle" else payload
                verified = verify_origin(doc, origin, root)
                self.assertEqual(origin["capture"]["source_asset"]["url"], str(doc.source_url))
                results[doc.doc_id] = (mode, doc.version, sum(p["kind"] == "source_text" for p in verified["segments"]))
                if doc.doc_id == "NHC-FLU-CARE-20250117":
                    self.assertEqual(old.body.replace("传感给他人", "传染给他人"), doc.body)
                else:
                    self.assertEqual(old.body, doc.body)
            self.assertEqual(results, {"BJ-DIARRHEA-20210406": ("origin", 1, 1),
                                      "NHC-FLU-CARE-20250117": ("bundle", 2, 2),
                                      "NHC-THROAT-20240821": ("bundle", 2, 3)})
