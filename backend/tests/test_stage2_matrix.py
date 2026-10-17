"""Runner bookkeeping/fault tests. These do not count as real model runs."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from medical.experiment import MEDICAL, load_suite, run_experiment
from medical.evaluation.metrics import validate_references
from medical.knowledge_base import load_corpus
from medical.stage2_matrix import run


class Stage2MatrixTests(unittest.TestCase):
    def test_new_long_input_cases_have_frozen_hashes_and_valid_evidence(self):
        _, groups = load_suite(MEDICAL/"evaluation/suite_v5.json")
        self.assertEqual(sum(map(len, groups.values())), 274)
        cases = groups["token-input-regression"]
        self.assertEqual(len(cases), 16)
        validate_references(cases, load_corpus(MEDICAL/"source_corpus"))
        self.assertTrue(any(len(c["query"]) > 1000 for c in cases))

    def test_invalid_experiment_tokens_are_recorded_before_loading_any_model(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"failure.json"
            with self.assertRaisesRegex(ValueError, "token settings"):
                run_experiment(MEDICAL/"evaluation/suite_v5.json", MEDICAL/"source_corpus", output, rerank_max_length=513)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(report["complete"])
            self.assertEqual(report["requested"]["rerank_max_length"], 513)
            self.assertEqual(report["failure_type"], "ValueError")

    def test_resume_preserves_failed_attempt_and_skips_completed_selection(self):
        def invoke(args, **kwargs):
            output = Path(args[args.index("--output")+1])
            failed = output.name.endswith("01.json")
            with output.open("x", encoding="utf-8") as handle:
                json.dump({"complete": not failed, "failure_type": "MemoryBudgetError" if failed else None}, handle)
            return SimpleNamespace(returncode=1 if failed else 0)
        with tempfile.TemporaryDirectory() as directory, patch("medical.stage2_matrix.repository_version",
                return_value={"commit": "fixture", "tracked_changes": False}), patch("medical.stage2_matrix.subprocess.run", side_effect=invoke) as child:
            folder = Path(directory)
            first = run(folder, ["legacy-256"])
            self.assertEqual(first["attempts"]["legacy-256"][0]["state"], "awaiting_memory")
            original = (folder/"legacy-256_attempt01.json").read_bytes()
            second = run(folder, ["legacy-256"], resume=True)
            self.assertTrue(second["attempts"]["legacy-256"][1]["complete"])
            self.assertFalse(second["complete"])
            run(folder, ["legacy-256"], resume=True)
            self.assertEqual(child.call_count, 2)
            self.assertEqual((folder/"legacy-256_attempt01.json").read_bytes(), original)
            with patch("medical.stage2_matrix.repository_version", return_value={"commit": "changed", "tracked_changes": False}):
                with self.assertRaisesRegex(ValueError, "code/data/config changed"):
                    run(folder, resume=True)

    def test_concurrent_resume_cannot_start_another_model_job(self):
        with tempfile.TemporaryDirectory() as directory, patch("medical.stage2_matrix.repository_version",
                return_value={"commit": "fixture", "tracked_changes": False}):
            folder = Path(directory)
            def invoke(args, **kwargs):
                with self.assertRaisesRegex(RuntimeError, "another process owns"):
                    run(folder, ["legacy-256"], resume=True)
                output = Path(args[args.index("--output")+1])
                output.write_text('{"complete":true}', encoding="utf-8")
                return SimpleNamespace(returncode=0)
            with patch("medical.stage2_matrix.subprocess.run", side_effect=invoke) as child:
                run(folder, ["legacy-256"])
                self.assertEqual(child.call_count, 1)


if __name__ == "__main__": unittest.main()
