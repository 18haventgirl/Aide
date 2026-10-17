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

    def test_snapshot_upgrade_does_not_mutate_the_historical_backlog(self):
        documents = load_corpus(MEDICAL/"source_corpus")
        # Metadata-only fixture: the inventory never judges clinical text quality.
        extra = documents[0].model_copy(update={"doc_id": "NHC-SLEEP-CORE-20250318"})
        expanded = inventory(documents+[extra], date(2026, 10, 17))
        baseline = inventory(documents, date(2026, 10, 17))
        sleep = lambda report: next(t for t in report["topics"] if t["id"] == "sleep")
        self.assertIn(extra.doc_id, sleep(expanded)["source_ids"])
        self.assertNotIn(extra.doc_id, sleep(baseline)["source_ids"])
        self.assertEqual(sleep(expanded)["status"], "partial_source_scope")


if __name__ == "__main__": unittest.main()
