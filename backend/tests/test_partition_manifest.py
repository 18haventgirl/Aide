"""Synthetic source snapshots verify sealing contracts, never model quality."""
from contextlib import ExitStack, redirect_stdout
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from medical.evaluation.partition_manifest import audit_partition_manifest, main, seal_partitions
from medical.knowledge_base import load_corpus
from medical.source_provenance import body_hash
from tests import test_source_snapshot as source_fixtures


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.snapshot, medical, self.raw, _ = source_fixtures.SnapshotTests().make_snapshot(self.root)
        self.data = self.root/"cases"; self.data.mkdir()
        self.development, self.validation, self.exposed = [self.data/name for name in ("dev.json", "val.json", "exposed.json")]
        self.output = self.data/"seal-v1.json"
        doc = next(d for d in load_corpus(self.snapshot/"corpus") if d.doc_id == "A")
        self.doc = doc
        start = doc.body.index("明确结论。")
        ref = {"doc_id": doc.doc_id, "version": doc.version, "body_sha256": body_hash(doc.body),
               "ranges": [[start, start+len("明确结论。")]]}
        base = {"kind": "supported", "topic": "synthetic", "authorship": "synthetic_contract_fixture",
                "expected_doc_ids": [doc.doc_id], "expected_evidence": [ref]}
        self.dev_case = {**copy.deepcopy(base), "id": "DEV1", "query": "家庭物品如何保留原包装？",
                         "family_id": "packaging", "template_id": "packaging_v1", "split": "development", "exposed_for_changes": True}
        self.val_case = {**copy.deepcopy(base), "id": "VAL1", "query": "新的变化需要关注哪些信号？",
                         "family_id": "observation", "template_id": "observation_v1", "split": "validation", "exposed_for_changes": False}
        self.old_case = {"id": "OLD1", "query": "某个未覆盖的合成主题是什么？", "kind": "unanswerable", "expected_doc_ids": []}
        self.write(self.development, [self.dev_case]); self.write(self.validation, [self.val_case]); self.write(self.exposed, [self.old_case])
        self.code = {"commit": "synthetic-commit", "tracked_changes": False, "untracked_bound_files": [],
                     "files_sha256": {"checker.py": "0"*64}}
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch("medical.audit_source_snapshot.ROOT", self.root))
        stack.enter_context(patch("medical.audit_source_snapshot.MEDICAL", medical))
        stack.enter_context(patch("medical.evaluation.partition_manifest.code_binding", side_effect=lambda: copy.deepcopy(self.code)))
        self.roots = {"data_root": self.data, "snapshot_root": self.root, "raw_root": self.raw}

    def write(self, path, data):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

    def seal(self, **kwargs):
        return seal_partitions(self.development, self.validation, exposure_paths=[self.exposed],
                               snapshot=self.snapshot, output=self.output, **self.roots, **kwargs)

    def audit(self):
        return audit_partition_manifest(self.output, **self.roots)

    def test_round_trip_binds_inputs_and_audit_is_read_only(self):
        seal = self.seal()
        before = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        report = self.audit()
        after = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(report["valid"])
        self.assertEqual(report["counts"], {"development": 1, "validation": 1})
        self.assertEqual(seal["metric_contract"], "source-evidence-v1")
        self.assertIn("not_external_blind", seal["status"])
        self.assertTrue(any("no retrieval" in value for value in report["limitations"]))
        with self.assertRaises(FileExistsError):
            self.seal()

    def test_original_file_bytes_are_locked_even_when_json_semantics_are_same(self):
        self.seal()
        self.validation.write_bytes(self.validation.read_bytes()+b"\n")
        with self.assertRaisesRegex(ValueError, "sealed case file changed"):
            self.audit()

    def test_source_capture_and_source_manifest_changes_are_detected(self):
        self.seal()
        target = self.snapshot/"snapshot_manifest.json"
        target.write_bytes(target.read_bytes()+b"\n")
        with self.assertRaisesRegex(ValueError, "source snapshot changed"):
            self.audit()
        target.write_bytes(target.read_bytes()[:-1])
        (self.raw/"capture.txt").write_text("changed source", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "capture hash differs"):
            self.audit()

    def test_exposure_ledger_changes_and_known_question_relabelling_are_rejected(self):
        old = {**self.val_case, "id": "RENAMED", "family_id": "renamed", "template_id": "renamed_template"}
        self.write(self.exposed, [old])
        with self.assertRaisesRegex(ValueError, "exposed_query_and_facts_reused"):
            self.seal()
        self.assertFalse(self.output.exists())
        self.write(self.exposed, [self.old_case]); self.seal()
        self.write(self.exposed, [{**self.old_case, "query": "changed historical question"}])
        with self.assertRaisesRegex(ValueError, "exposure file changed"):
            self.audit()

    def test_editorial_heading_and_unmapped_gold_cannot_be_sealed(self):
        start = self.doc.body.index("编辑范围")
        case = copy.deepcopy(self.val_case)
        case["expected_evidence"][0]["ranges"] = [[start, start+4]]
        self.write(self.validation, [case])
        with self.assertRaisesRegex(ValueError, "editorial"):
            self.seal()
        case = copy.deepcopy(self.val_case)
        case["expected_doc_ids"] = ["NEW-SOURCE"]
        case["expected_evidence"][0]["doc_id"] = "NEW-SOURCE"
        self.write(self.validation, [case])
        with self.assertRaisesRegex(ValueError, "origin is missing"):
            self.seal()

    def test_author_and_explicit_no_evidence_reason_are_required(self):
        case = copy.deepcopy(self.val_case); case.pop("authorship")
        self.write(self.validation, [case])
        with self.assertRaisesRegex(ValueError, "authorship"):
            self.seal()
        case.update(authorship="synthetic", kind="unanswerable", expected_doc_ids=[], expected_evidence=[])
        self.write(self.validation, [case])
        with self.assertRaisesRegex(ValueError, "no_evidence_reason"):
            self.seal()
        case["no_evidence_reason"] = "synthetic corpus has no supporting content"
        self.write(self.validation, [case])
        self.assertTrue(self.seal()["mechanical_checks"]["valid"])

    def test_implementation_changes_require_new_seal_but_documentation_commit_does_not(self):
        self.seal(); self.code["commit"] = "documentation-only"
        self.assertTrue(self.audit()["valid"])
        self.code["files_sha256"]["checker.py"] = "1"*64
        with self.assertRaisesRegex(ValueError, "implementation changed"):
            self.audit()

    def test_missing_exposure_registry_fails_before_sealing(self):
        with self.assertRaisesRegex(ValueError, "exposure registry"):
            seal_partitions(self.development, self.validation, exposure_paths=[], snapshot=self.snapshot,
                            output=self.output, **self.roots)
        self.assertFalse(self.output.exists())

    def test_sealed_paths_cannot_escape_declared_roots(self):
        self.seal()
        original = json.loads(self.output.read_text(encoding="utf-8"))
        for path in ("../outside.json", str(self.validation)):
            manifest = copy.deepcopy(original); manifest["partitions"]["validation"]["path"] = path
            self.write(self.output, manifest)
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "root|relative"):
                self.audit()

    def test_contract_metadata_and_saved_check_results_cannot_silently_drift(self):
        self.seal()
        original = json.loads(self.output.read_text(encoding="utf-8"))
        for field, value, message in (("schema_version", True, "contract"),
                                       ("metric_contract", "legacy-doc-v3", "contract"),
                                       ("mechanical_checks", {}, "result changed")):
            manifest = copy.deepcopy(original); manifest[field] = value; self.write(self.output, manifest)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                self.audit()

    def test_cli_invalid_manifest_returns_machine_readable_failure(self):
        self.output.write_text("{}", encoding="utf-8")
        output = io.StringIO()
        argv = ["partition_manifest", "audit", "--manifest", str(self.output), "--data-root", str(self.data)]
        with patch("sys.argv", argv), redirect_stdout(output), self.assertRaises(SystemExit) as caught:
            main()
        self.assertEqual(caught.exception.code, 1)
        self.assertFalse(json.loads(output.getvalue())["valid"])


if __name__ == "__main__":
    unittest.main()
