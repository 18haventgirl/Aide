"""Corrupted or partial source snapshots must never pass origin acceptance."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from medical.experiment import digest
from medical.audit_source_snapshot import audit_snapshot
from medical.experiment import prepare_origin_contract, run_experiment, MEDICAL
from medical.knowledge_base import load_corpus
from medical.source_provenance import body_hash
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

    def test_strict_experiment_preflight_rejects_editorial_and_missing_gold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); snapshot, medical, raw, _ = self.make_snapshot(root)
            docs = load_corpus(snapshot/"corpus")
            doc = next(d for d in docs if d.doc_id != "NEW-SOURCE")
            def case(text):
                start = doc.body.index(text)
                return {"id": "fixture", "query": "合成问题", "expected_doc_ids": [doc.doc_id],
                        "expected_evidence": [{"doc_id": doc.doc_id, "version": doc.version,
                            "body_sha256": body_hash(doc.body), "ranges": [[start, start+len(text)]]}]}
            with patch("medical.audit_source_snapshot.ROOT", root), patch("medical.audit_source_snapshot.MEDICAL", medical):
                audit, origins = prepare_origin_contract("source-evidence-v1", snapshot, snapshot/"corpus", docs,
                                                         [case("明确结论。")], raw_root=raw)
                self.assertEqual(audit["origin_verified_documents"], len(origins))
                with self.assertRaisesRegex(ValueError, "editorial"):
                    prepare_origin_contract("source-evidence-v1", snapshot, snapshot/"corpus", docs,
                                             [case("编辑范围")], raw_root=raw)
                without_ranges = case("明确结论。"); without_ranges.pop("expected_evidence")
                with self.assertRaisesRegex(ValueError, "all positive"):
                    prepare_origin_contract("source-evidence-v1", snapshot, snapshot/"corpus", docs,
                                             [without_ranges], raw_root=raw)

    def test_origin_snapshot_cannot_be_silently_ignored_or_paired_with_another_corpus(self):
        with self.assertRaisesRegex(ValueError, "requires source-evidence-v1"):
            prepare_origin_contract("evidence-v1", Path("snapshot"), Path("corpus"), [], [])
        with self.assertRaisesRegex(ValueError, "matching isolated"):
            prepare_origin_contract("source-evidence-v1", Path("snapshot"), Path("different"), [], [])
        self.assertEqual(prepare_origin_contract("evidence-v1", None, Path("corpus"), [], []), (None, None))

    def test_strict_preflight_failure_is_recorded_before_any_model_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"failed.json"
            with self.assertRaisesRegex(ValueError, "matching isolated"):
                run_experiment(MEDICAL/"evaluation/suite_v5.json", MEDICAL/"source_corpus", path,
                               metric_contract="source-evidence-v1")
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(report["complete"])
            self.assertEqual(report["failure_type"], "ValueError")
            self.assertEqual(report["requested"]["metric_contract"], "source-evidence-v1")

    def test_development_pilot_keeps_its_declared_source_contract(self):
        from medical.experiment import load_suite
        manifest, groups = load_suite(MEDICAL/"evaluation/source_pilot_suite_v1.json")
        cases = groups["source-origin-pilot-development"]
        self.assertEqual(len(cases), 12)
        self.assertTrue(all(c["split"] == "development" and c["exposed_for_changes"] is True for c in cases))
        self.assertEqual(sum(c["kind"] == "followup" for c in cases), 2)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "declared metric contract"):
                run_experiment(MEDICAL/"evaluation/source_pilot_suite_v1.json", MEDICAL/"source_corpus",
                               Path(directory)/"wrong-contract.json")


if __name__ == "__main__": unittest.main()
