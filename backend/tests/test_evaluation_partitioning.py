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


if __name__ == "__main__": unittest.main()
