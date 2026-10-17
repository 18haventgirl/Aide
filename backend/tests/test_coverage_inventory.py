"""The backlog must not label general article mentions as full coverage."""
from datetime import date
import unittest

from medical.coverage_inventory import inventory
from medical.experiment import MEDICAL
from medical.knowledge_base import load_corpus


class CoverageTests(unittest.TestCase):
    def test_real_corpus_source_concentration_and_gaps_are_explicit(self):
        report = inventory(load_corpus(MEDICAL/"source_corpus"), date(2026, 10, 17))
        self.assertEqual(report["documents"], 72)
        self.assertEqual(report["distinct_source_urls"], 7)
        self.assertEqual(report["source_concentration"][0]["documents"], 66)
        self.assertEqual(sum(report["topic_status_counts"].values()), 19)
        self.assertFalse(any(t["status"] == "complete" for t in report["topics"]))

    def test_removed_reference_is_not_silently_described_as_covered(self):
        documents = load_corpus(MEDICAL/"source_corpus")
        with self.assertRaisesRegex(ValueError, "bindings changed"):
            inventory([d for d in documents if d.doc_id != "NHC-HL2024-39"], date(2026, 10, 17))


if __name__ == "__main__": unittest.main()
