import tempfile
import unittest
from pathlib import Path

from medical.import_usda_foundation import ARCHIVE, import_archive, lookup_nutrient
from medical.export_usda_graph import export_graph


class USDAFoundationTests(unittest.TestCase):
    def test_pinned_import_preserves_units_missing_values_and_provenance(self):
        if not ARCHIVE.exists():
            self.skipTest("pinned USDA archive is not installed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = import_archive(data_root=root)
            self.assertEqual(manifest["food_records"], 363)
            self.assertEqual(manifest["food_nutrient_records"], 15193)
            self.assertEqual(manifest["missing_amounts"], 27)
            self.assertEqual(manifest["null_placeholders_in_source"], 32)
            self.assertFalse(manifest["agent_enabled"])
            database = root / "structured" / "usda_foundation_2026-04-30.sqlite"
            row = lookup_nutrient(database, 321358, 1120)
            self.assertEqual(row["unit"], "µg")
            self.assertEqual(row["amount_per_100g"], 3.0)
            self.assertIsNone(lookup_nutrient(database, 321358, 999999))
            graph = export_graph(root)
            self.assertEqual(graph["foods"], 363)
            self.assertEqual(graph["edges"], 15193)
            self.assertTrue((root / "graph" / "usda_foundation_2026-04-30_nodes.csv").exists())

    def test_changed_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "fake.zip"
            archive.write_bytes(b"not the pinned source")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                import_archive(archive=archive, data_root=Path(directory))


if __name__ == "__main__":
    unittest.main()
