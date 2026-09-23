import csv
import tempfile
import unittest
from pathlib import Path

from medical.data_registry import REGISTRY_DIR, assert_answer_eligible, validate_registry


class MedicalDataRegistryTests(unittest.TestCase):
    def test_checked_in_registry_has_matching_rows_and_explicit_eligibility(self):
        report = validate_registry(REGISTRY_DIR)
        self.assertEqual(report["errors"], [])
        self.assertGreaterEqual(report["dataset_count"], 30)
        self.assertIn("medlineplus_topics", report["answer_eligible"])
        self.assertNotIn("opencmkg", report["answer_eligible"])

    def test_unknown_or_research_only_rights_fail_closed(self):
        with self.assertRaises(PermissionError):
            assert_answer_eligible("opencmkg")
        with self.assertRaises(PermissionError):
            assert_answer_eligible("missing")

    def test_validator_rejects_unsupported_answer_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for name in ("datasets.csv", "licenses.csv"):
                with (REGISTRY_DIR / name).open(encoding="utf-8", newline="") as source:
                    reader = csv.DictReader(source)
                    rows = list(reader)
                    fields = reader.fieldnames
                if name == "licenses.csv":
                    for row in rows:
                        if row["dataset_id"] == "opencmkg":
                            row["answer_eligible"] = "yes"
                with (target / name).open("w", encoding="utf-8", newline="") as destination:
                    writer = csv.DictWriter(destination, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(rows)
            report = validate_registry(target)
            self.assertTrue(any("opencmkg: answer eligibility" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
