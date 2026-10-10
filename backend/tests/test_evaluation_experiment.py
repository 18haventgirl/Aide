"""Evaluation contracts: fixed labels, top-K metrics and reproducible suites."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from medical.evaluate import evaluate, validate_cases
from medical.experiment import MEDICAL, load_suite, mode_comparisons, digest, validate_source_bindings
from medical.knowledge_base import load_corpus
from medical.evaluation.author_general_v1 import write_frozen


class Search:
    def __init__(self, ids):
        self.ids = ids
    def search(self, query, limit=20):
        return [SimpleNamespace(doc_id=did) for did in self.ids]


class EvaluationTests(unittest.TestCase):
    def test_mrr_is_zero_when_first_match_outside_top_k(self):
        result = evaluate(Search(["wrong", "target"]),
                          [{"id": "q", "query": "饮水常识", "expected_doc_ids": ["target"]}], 1)
        self.assertEqual(result["recall_at_1"], 0)
        self.assertEqual(result["mrr_at_1"], 0)
        self.assertEqual(result["details"][0]["first_match_rank"], 2)

    def test_document_dedup_and_multiple_relevant_labels(self):
        result = evaluate(Search(["A", "A", "B"]),
                          [{"id": "q", "query": "饮水常识", "expected_doc_ids": ["A", "B", "C"]}], 2)
        self.assertEqual(result["recall_at_2"], .667)
        self.assertEqual(result["mrr_at_2"], 1)
        self.assertEqual(result["ndcg_at_2"], 1)
        self.assertEqual(result["details"][0]["retrieved"], ["A", "B"])

    def test_no_positive_cases_are_not_reported_as_perfect_recall(self):
        result = evaluate(Search([]), [{"id": "q", "kind": "unanswerable", "query": "天气预报"}], 5)
        self.assertIsNone(result["recall_at_5"])
        self.assertIsNone(result["mrr_at_5"])
        self.assertEqual(result["unanswerable_rejection_rate"], 1)

    def test_invalid_cases_fail_before_search(self):
        case = {"id": "q", "query": "饮水常识", "expected_doc_ids": ["A"]}
        invalid = [[], [case, case], [{**case, "query": " "}],
                   [{**case, "expected_doc_ids": "A"}], [{**case, "expected_doc_ids": ["A", "A"]}],
                   [{**case, "forbidden_doc_ids": ["A"]}], [{**case, "kind": "unknown"}],
                   [{**case, "kind": "followup"}]]
        for cases in invalid:
            with self.subTest(cases=cases), self.assertRaises(ValueError):
                validate_cases(cases)

    def test_frozen_suite_hashes_and_counts(self):
        manifest, groups = load_suite(MEDICAL / "evaluation" / "suite_v1.json")
        self.assertEqual(sum(map(len, groups.values())), 154)
        self.assertEqual(manifest["authorship"], "developer_authored_not_external_blind")

    def test_case_hash_is_independent_of_line_endings_and_spacing(self):
        value = [{"id": "q", "query": "合成问题", "expected_doc_ids": ["A"]}]
        spaced = json.dumps(value, ensure_ascii=False, indent=2).replace("\n", "\r\n")
        self.assertEqual(digest(json.loads(spaced)), digest(value))

    def test_new_frozen_group_categories_and_source_bindings(self):
        _, groups = load_suite(MEDICAL / "evaluation" / "suite_v2.json")
        cases = groups["frozen-chinese-general"]
        self.assertEqual(len(cases), 80)
        self.assertEqual(sum(c.get("kind") == "supported" for c in cases), 64)
        self.assertEqual(sum(c.get("kind") == "unanswerable" for c in cases), 8)
        self.assertEqual(sum(c.get("kind") == "urgent" for c in cases), 4)
        self.assertEqual(sum(c.get("kind") == "followup" for c in cases), 4)
        corpus = load_corpus(MEDICAL / "source_corpus")
        validate_source_bindings(cases, corpus)
        changed = [doc.model_copy(update={"body": doc.body + "变更"}) for doc in corpus]
        with self.assertRaisesRegex(ValueError, "frozen source changed"):
            validate_source_bindings(cases, changed)

    def test_authoring_cannot_overwrite_frozen_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            write_frozen(path, [{"label": "original"}])
            write_frozen(path, [{"label": "original"}])
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                write_frozen(path, [{"label": "changed"}])

    def test_source_bindings_cannot_silently_skip_invalid_metadata(self):
        corpus = load_corpus(MEDICAL / "source_corpus")
        _, groups = load_suite(MEDICAL / "evaluation" / "suite_v2.json")
        case = groups["frozen-chinese-general"][0]
        for binding in (None, {}, {**case["source_binding"], "doc_id": []},
                        {**case["source_binding"], "doc_id": "missing"}):
            with self.subTest(binding=binding), self.assertRaisesRegex(ValueError, "invalid source binding"):
                validate_source_bindings([{**case, "source_binding": binding}], corpus)
        with self.assertRaisesRegex(ValueError, "frozen source changed"):
            validate_source_bindings([{**case, "source_binding": {**case["source_binding"],
                                     "source_locator": "wrong paragraph"}}], corpus)

    def test_changed_case_file_or_manifest_count_fails(self):
        source = MEDICAL / "evaluation" / "suite_v1.json"
        manifest = json.loads(source.read_text(encoding="utf-8"))
        for entry in manifest["groups"]:
            entry["path"] = str((source.parent / entry["path"]).resolve())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "suite.json"
            original = manifest["groups"][0]["sha256"]
            manifest["groups"][0]["sha256"] = "0" * 64
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                load_suite(path)
            manifest["groups"][0]["sha256"] = original
            manifest["groups"][0]["count"] = 0
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "count mismatch"):
                load_suite(path)

    def test_comparisons_do_not_mix_groups_and_skip_unmeasured_metrics(self):
        results = {"topic": {"dense": {"recall_at_5": .7}, "hybrid": {"recall_at_5": .6}},
                   "other": {"rerank": {"recall_at_5": 1}}}
        rows = mode_comparisons(results, 5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["deltas"], {"recall_at_5": -.1})
        self.assertEqual(digest({"b": 2, "a": 1}), digest({"a": 1, "b": 2}))


if __name__ == "__main__":
    unittest.main()
