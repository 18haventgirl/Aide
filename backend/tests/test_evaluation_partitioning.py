"""Independent-set bookkeeping contracts; no real answer quality is measured."""
import unittest

from medical.evaluation.partitioning import normalized_query, validate_partitions
from tests.test_evidence_contract import document, reference


def case(identifier, split, query, family):
    doc = document()
    return {"id": identifier, "split": split, "query": query, "kind": "supported",
            "family_id": family, "template_id": family+"-template", "topic": "合成测试",
            "exposed_for_changes": split == "development", "expected_doc_ids": [doc.doc_id],
            "expected_evidence": [reference(doc)]}


class PartitionTests(unittest.TestCase):
    def setUp(self):
        self.dev = case("DEV1", "development", "怎样管理家庭物品的原包装？", "packaging")
        self.val = case("VAL1", "validation", "夜间出现新的情况应该关注哪些变化？", "observation")

    def test_shared_corpus_is_allowed_but_claim_is_not_external_blind(self):
        report = validate_partitions({"development": [self.dev], "validation": [self.val]}, [document()])
        self.assertTrue(report["valid"])
        self.assertEqual(report["shared_source_ids"], ["A"])
        self.assertIn("not_external_blindness", report["scope"])

    def test_family_and_template_leakage_cannot_be_renamed_as_new_validation(self):
        val = {**self.val, "family_id": self.dev["family_id"], "template_id": self.dev["template_id"]}
        report = validate_partitions({"development": [self.dev], "validation": [val]}, [document()])
        self.assertFalse(report["valid"])
        self.assertIn("cross_split_family_id", {e["reason"] for e in report["errors"]})
        self.assertIn("cross_split_template_id", {e["reason"] for e in report["errors"]})

    def test_near_duplicate_and_unicode_punctuation_checks(self):
        val = {**self.val, "query": self.dev["query"].replace("？", "?! ")}
        report = validate_partitions({"development": [self.dev], "validation": [val]}, [document()])
        self.assertFalse(report["valid"])
        self.assertTrue(report["near_duplicates_requiring_review"])
        self.assertEqual(normalized_query({"query": "12 片"}), normalized_query({"query": "１２片"}))
        self.assertNotEqual(normalized_query({"query": "12片"}), normalized_query({"query": "2片"}))

    def test_exposed_cases_and_missing_ranges_fail_closed(self):
        val = {**self.val, "exposed_for_changes": True, "expected_evidence": []}
        report = validate_partitions({"development": [self.dev], "validation": [val]}, [document()])
        self.assertFalse(report["valid"])
        reasons = {e["reason"] for e in report["errors"]}
        self.assertIn("validation_exposure_unverified_or_exposed", reasons)
        self.assertIn("positive_sources_need_exact_range_labels", reasons)

    def test_prior_exposure_cannot_be_hidden_by_new_ids_or_metadata(self):
        prior = {**self.val, "id": "OLD1", "split": "development", "exposed_for_changes": True,
                 "family_id": "old-family", "template_id": "old-template"}
        report = validate_partitions({"development": [self.dev], "validation": [self.val]},
                                     [document()], exposure_sets={"previous-cases": [prior]})
        self.assertFalse(report["valid"])
        self.assertEqual(report["exposure_sets_checked"], {"previous-cases": 1})
        self.assertIn("exposed_query_and_facts_reused", report["prior_exposure_matches"][0]["reasons"])

    def test_prior_family_and_template_reuse_are_checked_separately_from_text(self):
        prior = {**self.dev, "family_id": self.val["family_id"], "template_id": self.val["template_id"]}
        report = validate_partitions({"development": [self.dev], "validation": [self.val]},
                                     [document()], exposure_sets={"old": [prior]})
        reasons = report["prior_exposure_matches"][0]["reasons"]
        self.assertIn("exposed_family_id_reused", reasons)
        self.assertIn("exposed_template_id_reused", reasons)

    def test_unused_history_cannot_disguise_actual_duplicate_model_inputs(self):
        val = {**self.val, "query": self.dev["query"], "history": "这个前文在supported题中不会发给检索器。"}
        report = validate_partitions({"development": [self.dev], "validation": [val]}, [document()])
        reasons = {e["reason"] for e in report["errors"]}
        self.assertIn("history_unused_by_query_contract", reasons)
        self.assertIn("duplicate_query_and_facts", reasons)
        self.assertEqual(normalized_query(self.dev), normalized_query(val))
        # Effective followup facts remain separate and do change retrieval input.
        self.assertNotEqual(normalized_query(val), normalized_query({**val, "kind": "followup"}))

    def test_unknown_negative_document_and_nonboolean_exposure_fail(self):
        val = {**self.val, "forbidden_doc_ids": ["UNKNOWN"], "exposed_for_changes": 0}
        report = validate_partitions({"development": [self.dev], "validation": [val]}, [document()])
        reasons = {e["reason"] for e in report["errors"]}
        self.assertIn("unknown_forbidden_source", reasons)
        self.assertIn("validation_exposure_unverified_or_exposed", reasons)

    def test_invalid_similarity_thresholds_are_rejected(self):
        for threshold in (True, float("nan"), 0.1, 1.1):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                validate_partitions({"development": [self.dev], "validation": [self.val]},
                                    [document()], similarity_threshold=threshold)


if __name__ == "__main__": unittest.main()
