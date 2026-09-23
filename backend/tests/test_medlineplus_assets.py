import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from medical.export_medlineplus_assets import export_assets
from medical.import_medlineplus import DEFAULT_ARCHIVE, EXPANSION_TOPICS, TOPICS
from medical.chat import is_out_of_scope


class MedlinePlusAssetTests(unittest.TestCase):
    def test_photo_diagnosis_stays_out_of_retrieval_scope(self):
        self.assertTrue(is_out_of_scope("帮我看一下这张皮肤照片到底是什么病。"))

    def test_export_preserves_source_and_license_on_every_chunk(self):
        if not DEFAULT_ARCHIVE.exists():
            self.skipTest("pinned local MedlinePlus archive is not installed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = export_assets(root, collected_at=date(2026, 9, 24))
            self.assertEqual(report["documents"], len(TOPICS))
            self.assertEqual(len(EXPANSION_TOPICS), 50)
            path = root / "rag" / "medlineplus_topics_2026-09-19.jsonl"
            chunks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(chunks), report["chunks"])
            self.assertEqual(len({row["chunk_id"] for row in chunks}), len(chunks))
            self.assertTrue(all(row["source_url"].startswith("https://medlineplus.gov/") for row in chunks))
            self.assertTrue(all(row["license_id"] == "medlineplus_topics" for row in chunks))
            self.assertTrue(all(not row["clinical_reviewed"] for row in chunks))


if __name__ == "__main__":
    unittest.main()
