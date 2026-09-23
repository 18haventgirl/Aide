import json
import unittest
from types import SimpleNamespace

from medical.grounding import medical_response_metadata


class MedicalGroundingTests(unittest.TestCase):
    def test_extracts_and_deduplicates_sources_without_evidence_text(self):
        payload = {
            "query": "private health question",
            "knowledge_status": "grounded",
            "hits": [
                {"evidence_id": "E1", "doc_id": "A", "title": "资料A",
                 "text": "sensitive excerpt", "source_url": "https://example.org/a",
                 "source_org": "机构", "status": "source_checked"},
                {"evidence_id": "E2", "doc_id": "A", "title": "资料A",
                 "text": "another excerpt", "source_url": "https://example.org/a",
                 "source_org": "机构", "status": "source_checked"},
            ],
        }
        result = medical_response_metadata(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(result["knowledge_status"], "grounded")
        self.assertEqual(len(result["citations"]), 1)
        self.assertNotIn("query", result)
        self.assertNotIn("text", result["citations"][0])

    def test_understands_mcp_text_content_shape(self):
        wrapped = SimpleNamespace(content=[SimpleNamespace(text=json.dumps({
            "knowledge_status": "not_covered", "hits": [],
        }))])
        self.assertEqual(medical_response_metadata(wrapped), {
            "knowledge_status": "not_covered", "citations": [],
            "medical_urgency": None, "medical_scope": None,
        })

    def test_ignores_non_medical_tool_output(self):
        self.assertIsNone(medical_response_metadata('{"temperature": 25}'))


if __name__ == "__main__":
    unittest.main()
