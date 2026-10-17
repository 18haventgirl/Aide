"""Corrupted or partial source snapshots must never pass origin acceptance."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from medical.experiment import digest
from medical.audit_source_snapshot import audit_snapshot
from tests.test_source_origins import fixture


class SnapshotTests(unittest.TestCase):
    def make_snapshot(self, root):
        raw = root/"raw"; raw.mkdir()
        old, origin = fixture(raw)
        new = old.model_copy(update={"doc_id": "NEW-SOURCE", "title": "新增资料"})
        snapshot = root/"snapshot"
        medical = root/"medical"
        (snapshot/"corpus").mkdir(parents=True)
        (snapshot/"origins").mkdir()
        (medical/"source_corpus").mkdir(parents=True)
        for doc in (old, new):
            (snapshot/"corpus"/f"{doc.doc_id}.json").write_text(doc.model_dump_json(indent=2), encoding="utf-8")
        (medical/"source_corpus"/f"{old.doc_id}.json").write_bytes((snapshot/"corpus"/f"{old.doc_id}.json").read_bytes())
        (snapshot/"origins"/f"{old.doc_id}.json").write_text(json.dumps(origin), encoding="utf-8")
        docs = sorted((old, new), key=lambda d: d.doc_id)
        state = {"complete": True, "documents": 2, "corpus_sha256": digest([d.model_dump(mode="json") for d in docs]),
                 "origins_sha256": digest({old.doc_id: origin}), "origin_manifests_pending": [new.doc_id],
                 "origin_verified_documents": 1, "baseline_corpus_sha256": digest([old.model_dump(mode="json")]),
                 "changed_documents": [], "added_documents": 1, "added_doc_id": new.doc_id, "code": {"commit": "fixture"}}
        target = snapshot/"snapshot_manifest.json"
        target.write_text(json.dumps(state), encoding="utf-8")
        return snapshot, medical, raw, state

    def audit(self, root, snapshot, medical, raw):
        with patch("medical.audit_source_snapshot.ROOT", root), patch("medical.audit_source_snapshot.MEDICAL", medical):
            return audit_snapshot(snapshot, raw)

    def test_pending_origin_is_reported_and_not_counted_as_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); snapshot, medical, raw, _ = self.make_snapshot(root)
            report = self.audit(root, snapshot, medical, raw)
            self.assertEqual(report["origin_verified_documents"], 1)
            self.assertEqual(report["pending_origin_documents"], ["NEW-SOURCE"])
            self.assertEqual(report["unchanged_historical_files"], 1)
            self.assertFalse(report["release_ready"])

    def test_partial_and_misdeclared_coverage_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); snapshot, medical, raw, state = self.make_snapshot(root)
            for mutation, message in (({"complete": False}, "incomplete"),
                                      ({"origin_verified_documents": 2}, "coverage declaration"),
                                      ({"added_doc_id": "wrong"}, "added document")):
                (snapshot/"snapshot_manifest.json").write_text(json.dumps({**state, **mutation}), encoding="utf-8")
                with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, message):
                    self.audit(root, snapshot, medical, raw)

    def test_changed_sidecar_is_rejected_even_when_canonical_corpus_is_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); snapshot, medical, raw, _ = self.make_snapshot(root)
            path = next((snapshot/"origins").glob("*.json"))
            value = json.loads(path.read_text(encoding="utf-8")); value["segments"][0]["kind"] = "editorial_heading"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sidecars differ"):
                self.audit(root, snapshot, medical, raw)

    def test_changed_raw_capture_cannot_be_hidden_by_unchanged_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); snapshot, medical, raw, _ = self.make_snapshot(root)
            (raw/"capture.txt").write_text("被改过的内容", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "capture hash differs"):
                self.audit(root, snapshot, medical, raw)


if __name__ == "__main__": unittest.main()
