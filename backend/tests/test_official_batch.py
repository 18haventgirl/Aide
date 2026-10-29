"""Reviewed HTML selections must retain literal provenance without invented text."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from medical.capture_official_batch import build_bundle
from medical.experiment import digest
from medical.schema import MedicalDocument
from medical.source_origins import OriginResolver, validate_literal_references, verify_origin
from medical.source_pipeline import paragraphs
from medical.source_provenance import body_hash
from tests.test_evidence_contract import document


def fixture(raw_root):
    html = ("<html><body><p>原始小节</p><p>未选入的人群内容。</p>"
            "<p>来源中的<strong>明确结论</strong>。\n  条件甲 &amp; 条件乙。</p>"
            "<p>未选入的具体处置。</p><p>变化时的求助提示。🧪</p></body></html>").encode("utf-8")
    captured = ("\n\n".join(paragraphs(html.decode("utf-8")))+"\n").encode("utf-8")
    (raw_root/"page.html").write_bytes(html)
    (raw_root/"capture.txt").write_bytes(captured)
    metadata = document(did="BATCH-FIXTURE").model_dump(mode="json")
    # Deliberately use a title that also occurs in the source: matching text
    # alone must not grant the generated title literal source provenance.
    metadata["title"] = "原始小节"
    metadata.pop("body")
    metadata.pop("source_sha256")
    metadata.pop("source_url")
    return {"html_path": "page.html", "html_sha256": hashlib.sha256(html).hexdigest(),
            "capture_path": "capture.txt", "capture_sha256": hashlib.sha256(captured).hexdigest(),
            "paragraph_count": 5, "source_url": "https://example.org/official-fixture",
            "selected_paragraphs": [0, 2, 4], "heading_paragraphs": [0],
            "omitted_paragraphs": {"1": "synthetic subgroup omitted", "3": "synthetic treatment omitted"},
            "document": metadata}


class OfficialBatchTests(unittest.TestCase):
    def test_exact_selection_tracks_unicode_source_ranges_and_omissions(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory); spec = fixture(raw_root)
            before = {p.name: p.read_bytes() for p in raw_root.iterdir()}
            bundle = build_bundle(spec, raw_root)
            doc = MedicalDocument.model_validate(bundle["document"])
            origin = bundle["origin"]
            source = verify_origin(doc, origin, raw_root)["capture_text"]
            literal = [p for p in origin["segments"] if p["kind"].startswith("source_")]
            self.assertEqual([p["paragraph_index"] for p in literal], [0, 2, 4])
            self.assertEqual([p["kind"] for p in literal], ["source_heading", "source_text", "source_text"])
            for part in literal:
                a, b = part["body_range"]; x, y = part["capture_range"]
                self.assertEqual(doc.body[a:b], source[x:y])
            self.assertIn("明确结论。 条件甲 & 条件乙。", doc.body)
            self.assertTrue(doc.body.endswith("🧪"))
            self.assertNotIn("未选入", doc.body)
            self.assertEqual([p["paragraph_index"] for p in origin["omissions"]], [1, 3])
            for part in origin["omissions"]:
                self.assertTrue(source[slice(*part["capture_range"])].startswith("未选入"))
            self.assertEqual(doc.source_sha256, spec["html_sha256"])
            self.assertEqual(origin["capture"]["sha256"], spec["capture_sha256"])
            self.assertNotEqual(doc.source_sha256, origin["capture"]["sha256"])
            self.assertEqual(origin["selection_recipe_sha256"], digest(spec))
            self.assertFalse(origin["public_answer_eligible"])
            self.assertEqual(before, {p.name: p.read_bytes() for p in raw_root.iterdir()})

    def test_generated_title_is_rejected_as_gold_even_when_words_occur_in_source(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory); spec = fixture(raw_root)
            bundle = build_bundle(spec, raw_root)
            doc = MedicalDocument.model_validate(bundle["document"])
            resolver = OriginResolver([doc], {doc.doc_id: bundle["origin"]}, raw_root)
            ref = {"doc_id": doc.doc_id, "version": doc.version, "body_sha256": body_hash(doc.body),
                   "ranges": [[2, 2+len(doc.title)]]}
            cases = [{"id": "fixture", "kind": "supported", "query": "合成问题",
                      "expected_doc_ids": [doc.doc_id], "expected_evidence": [ref]}]
            with self.assertRaisesRegex(ValueError, "editorial/metadata"):
                validate_literal_references(cases, resolver)
            ref["ranges"] = [next(p["body_range"] for p in bundle["origin"]["segments"] if p["kind"] == "source_heading")]
            validate_literal_references(cases, resolver)

    def test_modified_original_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory); spec = fixture(raw_root)
            (raw_root/"page.html").write_bytes(b"<p>different</p>")
            with self.assertRaisesRegex(ValueError, "original HTML differs"):
                build_bundle(spec, raw_root)

    def test_forged_derived_text_is_rejected_even_with_matching_new_capture_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory); spec = fixture(raw_root)
            forged = "原始小节\n\n替换后的错误结论。\n".encode("utf-8")
            (raw_root/"capture.txt").write_bytes(forged)
            spec["capture_sha256"] = hashlib.sha256(forged).hexdigest()
            with self.assertRaisesRegex(ValueError, "original HTML extraction"):
                build_bundle(spec, raw_root)

    def test_declared_capture_hash_and_paragraph_count_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory); spec = fixture(raw_root)
            for changes, message in (({"capture_sha256": "0"*64}, "capture hash differs"),
                                     ({"paragraph_count": 5.0}, "paragraph extraction differs"),
                                     ({"paragraph_count": 6}, "paragraph extraction differs")):
                with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                    build_bundle({**spec, **changes}, raw_root)

    def test_selection_must_be_ordered_unique_and_headings_must_be_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory); spec = fixture(raw_root)
            changes = [{"selected_paragraphs": value} for value in ([], [0, 4, 2], [0, 2, 2, 4],
                         [0, True, 4], [-1, 2, 4], [0, 2, 5], ["0", 2, 4], None)]
            changes += [{"heading_paragraphs": value} for value in ([1], [0, 0], [False], ["0"], None)]
            for change in changes:
                with self.subTest(change=change), self.assertRaisesRegex(ValueError, "unique ordered"):
                    build_bundle({**spec, **change}, raw_root)

    def test_every_unselected_paragraph_needs_nonempty_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory); spec = fixture(raw_root)
            for omissions in ({}, {"1": "reason"}, {"1": "reason", "3": ""},
                              {"1": "reason", "3": "   "}, {"1": "reason", "3": None},
                              {"1": "reason", "3": "reason", "0": "selected"}, None):
                with self.subTest(omissions=omissions), self.assertRaisesRegex(ValueError, "omission reasons"):
                    build_bundle({**spec, "omitted_paragraphs": omissions}, raw_root)

    def test_original_and_capture_paths_cannot_escape_raw_root(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory); spec = fixture(raw_root)
            for field, filename in (("html_path", "page.html"), ("capture_path", "capture.txt")):
                for value in ("../outside"+Path(filename).suffix, str(raw_root/filename)):
                    with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "approved root"):
                        build_bundle({**spec, field: value}, raw_root)

    def test_selected_body_and_source_hash_are_built_from_assets_not_supplied_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_root = Path(directory); spec = fixture(raw_root)
            spec = copy.deepcopy(spec)
            spec["document"].update(body="injected text", source_url="https://example.org/wrong", source_sha256="0"*64)
            bundle = build_bundle(spec, raw_root)
            self.assertNotIn("injected text", bundle["document"]["body"])
            self.assertEqual(bundle["document"]["source_url"], spec["source_url"])
            self.assertEqual(bundle["document"]["source_sha256"], spec["html_sha256"])


if __name__ == "__main__":
    unittest.main()
