"""The archived HTML and legacy excerpt have different immutable hash roles."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from medical.capture_headache_origin import (DOC_ID, EXCERPT_SHA, ORIGINAL_PATH,
    ORIGINAL_SHA, RAW_ASSET, ROOT, build_origin, map_document_lines, save_original)
from medical.schema import MedicalDocument
from medical.source_origins import verify_origin
from tests.test_evidence_contract import document


class HeadacheOriginTests(unittest.TestCase):
    def test_generated_headings_cannot_borrow_a_substring_from_source_prose(self):
        doc = document(body="# 编写标题\n明确结论。\n# 原始章节\n下一句。")
        paragraphs = ["这里提到编写标题但它不是原始标题。", "明确结论。", "原始章节", "下一句。"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = ("\n\n".join(paragraphs)+"\n").encode()
            (root/"capture.txt").write_bytes(raw)
            capture = {"path": "capture.txt", "sha256": hashlib.sha256(raw).hexdigest(), "method": "fixture"}
            origin = map_document_lines(doc, paragraphs, capture)
            verify_origin(doc, origin, root)
            self.assertEqual([p["kind"] for p in origin["segments"]],
                             ["markup", "editorial_heading", "source_text", "markup", "source_heading", "source_text"])

    def test_body_lines_must_be_exact_unique_and_ordered(self):
        doc = document(body="第一句。\n第二句。")
        for paragraphs in (["第一句。", "其他句。"], ["第一句。", "第一句。", "第二句。"], ["第二句。", "第一句。"]):
            with self.subTest(paragraphs=paragraphs), self.assertRaisesRegex(ValueError, "unique ordered"):
                map_document_lines(doc, paragraphs, {})

    def test_original_copy_refuses_changed_bytes_and_paths_outside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_original(root, Path("p/original.html"), b"same")
            save_original(root, Path("p/original.html"), b"same")
            with self.assertRaisesRegex(ValueError, "never replace"):
                save_original(root, Path("p/original.html"), b"changed")
            with self.assertRaisesRegex(ValueError, "raw root"):
                save_original(root, Path("../outside.html"), b"same")
            with self.assertRaisesRegex(ValueError, "raw root"):
                save_original(root, root/"absolute.html", b"same")

    def test_changed_canonical_body_fails_before_original_read(self):
        doc = document(body="changed").model_copy(update={"doc_id": DOC_ID})
        with self.assertRaisesRegex(ValueError, "excerpt differs"):
            build_origin(doc, Path("unused"), Path("does-not-exist.html"))

    @unittest.skipUnless(ORIGINAL_PATH.is_file(), "local pinned official HTML not installed")
    def test_actual_source_preserves_both_hash_roles_body_and_exact_ranges(self):
        path = ROOT/f"backend/medical/source_corpus/{DOC_ID}.json"
        before_file = path.read_bytes()
        doc = MedicalDocument.model_validate_json(before_file)
        before = copy.deepcopy(doc.model_dump(mode="json"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            origin = build_origin(doc, root)
            self.assertEqual(origin, build_origin(doc, root))
            self.assertEqual(origin["source_asset_sha256"], EXCERPT_SHA)
            self.assertEqual(origin["capture"]["source_asset"]["sha256"], ORIGINAL_SHA)
            self.assertNotEqual(EXCERPT_SHA, ORIGINAL_SHA)
            self.assertEqual(origin["declared_source_hash_kind"], "utf8_canonical_excerpt_not_original_html")
            self.assertEqual((root/RAW_ASSET).read_bytes(), ORIGINAL_PATH.read_bytes())
            verified = verify_origin(doc, origin, root)
            counts = {kind: len([p for p in verified["segments"] if p["kind"] == kind])
                      for kind in ("source_text", "source_heading", "markup")}
            self.assertEqual(counts, {"source_text": 20, "source_heading": 2, "markup": 2})
            self.assertEqual(doc.model_dump(mode="json"), before)
            self.assertEqual(path.read_bytes(), before_file)
            (root/RAW_ASSET).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "never replace"):
                build_origin(doc, root)

    @unittest.skipUnless(ORIGINAL_PATH.is_file(), "local pinned official HTML not installed")
    def test_changed_original_fails_before_capture_creation(self):
        doc = MedicalDocument.model_validate_json((ROOT/f"backend/medical/source_corpus/{DOC_ID}.json").read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); changed = root/"input.html"
            changed.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "pinned headache HTML differs"):
                build_origin(doc, root/"raw", changed)
            self.assertFalse((root/"raw").exists())


if __name__ == "__main__":
    unittest.main()
