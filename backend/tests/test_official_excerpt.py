import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from medical.import_official_excerpt import build_documents
from medical.knowledge_base import MedicalKnowledgeBase


ROOT = Path(__file__).resolve().parents[2]


class OfficialExcerptTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "medical-rag-data/registry/chinese_symptoms_20260928.json").read_text(encoding="utf-8"))

    def test_changed_source_and_duplicate_fail_closed(self):
        changed = copy.deepcopy(self.manifest)
        changed["documents"][0]["body"] += "篡改"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            build_documents(changed)
        self.manifest["documents"].append(self.manifest["documents"][0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_documents(self.manifest)

    def test_reproducible_research_only_documents(self):
        for doc in build_documents(self.manifest):
            saved = ROOT / "backend/medical/source_corpus" / f"{doc.doc_id}.json"
            self.assertEqual(json.loads(saved.read_text(encoding="utf-8")), doc.model_dump(mode="json"))
            self.assertFalse(doc.is_searchable(doc.reviewed_at))
            self.assertTrue(doc.is_searchable(doc.reviewed_at, research_mode=True))

    def test_scope_reaches_tool_payload(self):
        doc = build_documents(self.manifest)[0]
        metadata = doc.model_dump(mode="json")
        metadata["section_path"] = "流感"
        candidate = {"chunk_id": "test", "metadata": metadata, "text": doc.body}
        hit = MedicalKnowledgeBase._to_hit(None, candidate)
        spec = importlib.util.spec_from_file_location("scope_medical_tools", ROOT / "backend/mcp-serve/medical_tools.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        class Capture:
            def tool(self, function):
                self.search = function
                return function
        capture = Capture()
        module.register_medical_tools(capture)
        with patch.object(module, "search_with_metrics", return_value=[hit]):
            result = json.loads(capture.search("流感期间怎么休息"))
        self.assertEqual(result["hits"][0]["usage_scope"], doc.usage_scope)


if __name__ == "__main__":
    unittest.main()
