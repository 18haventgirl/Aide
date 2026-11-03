"""Exercise the normal experiment entry point using synthetic labels, stopping before ML."""
import copy
from contextlib import redirect_stderr
import hashlib
import io
import json
import shutil
import unittest
from unittest.mock import patch

from medical.evaluate import QUERY_CONTRACT, main as legacy_evaluation_cli
from medical.experiment import digest, load_suite, run_experiment
from tests import test_partition_manifest as fixtures


class SealedRunTests(unittest.TestCase):
    def setUp(self):
        f = self.fixture = fixtures.ManifestTests()
        self.addCleanup(f.doCleanups)
        f.setUp()
        data = f.root / "medical-rag-data"
        datasets = data / "datasets"
        f.snapshot = shutil.copytree(f.snapshot, datasets / "synthetic-source")
        raw = shutil.copytree(f.raw, data / "raw")
        f.roots.update(snapshot_root=datasets, raw_root=raw)
        self.enterContext(patch("medical.experiment.MEDICAL", f.data))
        self.enterContext(patch("medical.experiment.ROOT", f.root))
        self.version = self.enterContext(patch("medical.evaluation.partition_manifest.repository_version",
                                               return_value={"retrieval_implementation_sha256": "e"*64}))
        self.memory = self.enterContext(patch("medical.resource_budget.require_available",
                                              side_effect=RuntimeError("synthetic stop before ML")))
        self.suite = f.data / "suite.json"
        self.options = {"profiles": ["hybrid", "rerank"], "k": 5, "rerank_max_length": 256,
                        "input_policy": "query_first_v1", "chunk_strategy": "token-v1", "child_tokens": 180}
        self.manifest = {"schema_version": 1, "hash_scheme": "canonical-json-v1", "suite_id": "synthetic",
                         "metric_contract": "source-evidence-v1", "query_contract": QUERY_CONTRACT,
                         "evaluation_date": "2026-11-02", "validation_config": self.options,
                         "groups": [{"name": "heldout", "purpose": "validation", "path": f.validation.name,
                                     "count": 1, "sha256": digest([f.val_case])}]}
        f.write(self.suite, self.manifest)

    def seal(self):
        f = self.fixture
        f.seal(validation_suite=self.suite)
        return hashlib.sha256(f.output.read_bytes()).hexdigest()

    def run_case(self, name, checksum, **overrides):
        f = self.fixture
        output = f.root / (name+".json")
        args = dict(manifest_path=self.suite, corpus_path=f.snapshot/"corpus", output=output,
                    metric_contract="source-evidence-v1", source_snapshot=f.snapshot,
                    partition_seal=f.output, seal_sha256=checksum, **self.options)
        run_experiment(**{**args, **overrides})

    def test_valid_registration_reaches_budget_guard_and_failure_retains_seal_identity(self):
        checksum = self.seal()
        with self.assertRaisesRegex(RuntimeError, "synthetic stop before ML"):
            self.run_case("guard", checksum)
        self.memory.assert_called_once_with(1536)
        report = json.loads((self.fixture.root/"guard.json").read_bytes())
        self.assertFalse(report["complete"])
        validation = report["validation"]
        self.assertEqual(validation["seal_sha256"], checksum)
        self.assertEqual(validation["validation_run"]["options"], self.options)
        self.assertEqual(validation["validation_file"]["canonical_json_sha256"], digest([self.fixture.val_case]))
        self.assertEqual(validation["source_snapshot"]["path"], "synthetic-source")

    def test_missing_or_wrong_seal_is_rejected_before_loading_suite_rows(self):
        checksum = self.seal()
        with patch("medical.experiment._load_suite") as load:
            for name, seal, sha, error in (("absent", None, checksum, "requires --partition-seal"),
                                           ("unpinned", self.fixture.output, None, "requires --partition-seal"),
                                           ("untrusted", self.fixture.output, "0"*64, "seal SHA256 differs")):
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, error):
                    self.run_case(name, sha, partition_seal=seal)
            load.assert_not_called()
        self.memory.assert_not_called()

    def test_unsealed_suite_loader_rejects_validation_before_reading_rows(self):
        # A missing row file would raise FileNotFoundError if the loader opened it.
        self.fixture.validation.unlink()
        with self.assertRaisesRegex(ValueError, "before loading cases"):
            load_suite(self.suite)

    def test_legacy_cases_cli_rejects_validation_before_requesting_knowledge_base(self):
        err = io.StringIO()
        with patch("sys.argv", ["medical.evaluate", "--cases", str(self.fixture.validation)]), \
                patch("medical.evaluate.get_knowledge_base") as kb, redirect_stderr(err):
            with self.assertRaises(SystemExit) as stopped:
                legacy_evaluation_cli()
        self.assertEqual(stopped.exception.code, 2)
        self.assertIn("verified partition seal", err.getvalue())
        kb.assert_not_called()

    def test_options_group_and_snapshot_cannot_drift(self):
        checksum = self.seal()
        for name, change, error in (
                ("smaller_k", {"k": 3}, "options differ"),
                ("drop_baseline", {"profiles": ["rerank"]}, "options differ"),
                ("child_budget", {"child_tokens": 220}, "options differ"),
                ("rerank_budget", {"rerank_max_length": 512}, "options differ"),
                ("group_subset", {"groups": ["another-group"]}, "entire registered group"),
                ("canonical_only", {"metric_contract": "evidence-v1"}, "strict source snapshot"),
                ("different_snapshot", {"source_snapshot": self.fixture.root/"copy"}, "snapshot differs"),
                ("different_corpus", {"corpus_path": self.fixture.root/"corpus"}, "snapshot differs")):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, error):
                self.run_case(name, checksum, **change)
        self.memory.assert_not_called()

    def test_label_or_implementation_change_blocks_execution(self):
        checksum = self.seal()
        self.version.return_value = {"retrieval_implementation_sha256": "f"*64}
        with self.assertRaisesRegex(ValueError, "implementation changed"):
            self.run_case("changed_code", checksum)
        self.fixture.write(self.fixture.validation, [{**self.fixture.val_case, "topic": "changed"}])
        with self.assertRaisesRegex(ValueError, "sealed case file changed"):
            self.run_case("changed_labels", checksum)
        self.memory.assert_not_called()

    def test_reclassifying_validation_as_development_or_forcing_seal_onto_development_fails(self):
        checksum = self.seal()
        modified = copy.deepcopy(self.manifest)
        modified["groups"][0]["purpose"] = "development"
        modified.pop("validation_config")
        self.fixture.write(self.suite, modified)
        with self.assertRaisesRegex(ValueError, "require a validation group"):
            self.run_case("relabelled", None, partition_seal=None)
        with self.assertRaisesRegex(ValueError, "dedicated validation suite"):
            self.run_case("forced", checksum)
        self.memory.assert_not_called()

    def test_archive_only_seal_cannot_authorize_validation(self):
        self.fixture.seal()
        checksum = hashlib.sha256(self.fixture.output.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "not registered"):
            self.run_case("archive_only", checksum)
        self.memory.assert_not_called()

    def test_changed_suite_and_equivalent_copy_at_different_path_are_rejected(self):
        checksum = self.seal()
        other = self.fixture.data / "copied-suite.json"
        other.write_bytes(self.suite.read_bytes())
        with self.assertRaisesRegex(ValueError, "not registered"):
            self.run_case("copied", checksum, manifest_path=other)
        self.fixture.write(self.suite, {**self.manifest, "evaluation_date": "2027-01-15"})
        with self.assertRaisesRegex(ValueError, "registered validation suite"):
            self.run_case("new_date", checksum)
        self.memory.assert_not_called()

    def test_registration_rejects_mixed_groups_and_copied_or_partial_validation_files(self):
        entry = self.manifest["groups"][0]
        for groups, error in (([entry, {**entry, "purpose": "development"}], "dedicated strict-source"),
                              ([{**entry, "path": self.fixture.development.name}], "sealed validation file"),
                              ([{**entry, "count": 0}], "entire sealed partition"),
                              ([{**entry, "allow_historical_missing_ids": True}], "exposure policy")):
            with self.subTest(groups=groups), self.assertRaisesRegex(ValueError, error):
                self.fixture.write(self.suite, {**self.manifest, "groups": groups})
                self.seal()
            self.assertFalse(self.fixture.output.exists())


if __name__ == "__main__":
    unittest.main()
