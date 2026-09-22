"""Core medical RAG invariants using local Chroma and deterministic embeddings."""

import unittest
from datetime import date

import chromadb
from pydantic import ValidationError

from medical.chunking import chunk_document
from medical.chat import is_urgent, needs_clinical_decision
from medical.knowledge_base import MedicalKnowledgeBase
from medical.schema import MedicalDocument


class TestEmbedding:
    def __call__(self, input):
        return [[float(len(text) % 17), float(sum(ord(c) for c in text) % 19), 1.0] for text in input]

    def name(self):
        return "test-medical-embedding"


class QueryAwareEmbedding(TestEmbedding):
    def __init__(self):
        self.documents_encoded = 0
        self.queries_encoded = 0

    def embed_documents(self, texts):
        self.documents_encoded += len(texts)
        return self(texts)

    def embed_queries(self, texts):
        self.queries_encoded += len(texts)
        return self(texts)


class ConstantEmbedding:
    def name(self):
        return "test-medical-embedding"

    def embed_documents(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]

    def embed_queries(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]

    def __call__(self, input):
        return self.embed_documents(input)


class KeywordReranker:
    def name(self):
        return "test-reranker"

    def score(self, query, passages):
        return [0.95 if "优先内容" in passage else 0.05 for passage in passages]


class BrokenReranker(KeywordReranker):
    def score(self, query, passages):
        raise RuntimeError("test failure")


def document(doc_id: str, status: str = "source_checked", version: int = 1,
             body: str = "# 饮水\n测试用文本：饮水与日常生活。") -> MedicalDocument:
    return MedicalDocument.model_validate({
        "doc_id": doc_id,
        "version": version,
        "title": "测试健康主题",
        "topic": "健康常识",
        "audience": "成年人",
        "source_org": "测试机构",
        "source_url": "https://example.org/health",
        "source_published_at": "2024-01-01",
        "status": status,
        "reviewer": "测试核对人" if status in {"source_checked", "clinician_reviewed"} else None,
        "reviewed_at": "2024-01-02" if status in {"source_checked", "clinician_reviewed"} else None,
        "next_review_at": "2099-01-01" if status in {"source_checked", "clinician_reviewed"} else None,
        "license_note": "仅供自动化测试",
        "source_sha256": "0" * 64 if status in {"source_checked", "clinician_reviewed"} else None,
        "source_locator": "测试段" if status in {"source_checked", "clinician_reviewed"} else None,
        "source_collected_at": "2024-01-01" if status in {"source_checked", "clinician_reviewed"} else None,
        "body": body,
    })


class MedicalRagTests(unittest.TestCase):
    def test_sections_do_not_mix_and_chunks_are_bounded(self):
        body = "# 第一节\n" + "喝水有益。" * 100 + "\n# 第二节\n" + "规律活动。" * 100
        chunks = chunk_document(body, "测试", max_chars=120, overlap=20)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(chunk.text) <= 120 for chunk in chunks))
        self.assertTrue(all("喝水" not in chunk.text for chunk in chunks if chunk.section_path == "第二节"))

    def test_review_gate_update_and_withdrawal(self):
        kb = MedicalKnowledgeBase(chromadb.EphemeralClient(), TestEmbedding(), "test-v1", research_mode=True)
        self.assertEqual(kb.sync([document("A"), document("B", "draft")])["indexed_documents"], 1)
        self.assertEqual(kb.collection.count(), 1)
        self.assertEqual(kb.search("饮水")[0].doc_id, "A")
        kb.sync([document("A", version=2), document("B", "draft")])
        self.assertEqual(kb.collection.count(), 1)
        kb.sync([document("A", "retired"), document("B", "draft")])
        self.assertEqual(kb.collection.count(), 0)

    def test_reviewed_document_requires_audit(self):
        bad = document("C").model_dump(mode="json")
        bad["reviewer"] = None
        with self.assertRaises(ValidationError):
            MedicalDocument.model_validate(bad)

    def test_expired_document_is_excluded(self):
        item = document("D").model_copy(update={"next_review_at": date(2020, 1, 1)})
        kb = MedicalKnowledgeBase(chromadb.EphemeralClient(), TestEmbedding(), "test-v1", research_mode=True)
        kb.sync([item], today=date(2026, 9, 16))
        self.assertEqual(kb.collection.count(), 0)

    def test_empty_corpus_cannot_wipe_index(self):
        kb = MedicalKnowledgeBase(chromadb.EphemeralClient(), TestEmbedding(), "test-v1", research_mode=True)
        kb.sync([document("E")])
        with self.assertRaises(ValueError):
            kb.sync([])
        self.assertEqual(kb.collection.count(), 1)

    def test_research_and_public_status_are_isolated(self):
        client = chromadb.EphemeralClient()
        embedding = QueryAwareEmbedding()
        research = MedicalKnowledgeBase(client, embedding, "test-v1", research_mode=True)
        public = MedicalKnowledgeBase(client, embedding, "test-v1")
        corpus = [document("R"), document("P", "clinician_reviewed")]
        self.assertEqual(research.sync(corpus)["indexed_documents"], 2)
        self.assertEqual(public.sync(corpus)["indexed_documents"], 1)
        self.assertEqual(research.collection.count(), 2)
        self.assertEqual(public.collection.count(), 1)
        self.assertEqual(public.search("饮水")[0].doc_id, "P")
        self.assertGreater(embedding.documents_encoded, 0)
        self.assertGreater(embedding.queries_encoded, 0)

    def test_withdrawn_document_is_removed(self):
        kb = MedicalKnowledgeBase(chromadb.EphemeralClient(), TestEmbedding(), "test-v1", research_mode=True)
        kb.sync([document("W")])
        withdrawn = document("W").model_copy(update={"withdrawn": True})
        kb.sync([withdrawn])
        self.assertEqual(kb.collection.count(), 0)

    def test_cross_encoder_controls_final_order(self):
        kb = MedicalKnowledgeBase(
            chromadb.EphemeralClient(), ConstantEmbedding(),
            "test-v1", research_mode=True,
            reranker=KeywordReranker(),
        )
        kb.max_distance = 0.50
        kb.use_lexical = True
        kb.sync([
            document("LOW", body="# 普通\n普通内容。"),
            document("HIGH", body="# 优先\n优先内容。"),
        ])
        hits = kb.search("内容", limit=2)
        self.assertEqual(hits[0].doc_id, "HIGH")
        self.assertIsNotNone(hits[0].rerank_score)
        self.assertEqual(kb.search_metrics()["reranker_status"], "applied")

    def test_reranker_failure_uses_hybrid_fallback(self):
        kb = MedicalKnowledgeBase(
            chromadb.EphemeralClient(), ConstantEmbedding(),
            "test-v1", research_mode=True,
            reranker=BrokenReranker(),
        )
        kb.max_distance = 0.50
        kb.use_lexical = True
        kb.sync([document("A")])
        self.assertEqual(kb.search("饮水", limit=1)[0].doc_id, "A")
        self.assertEqual(kb.search_metrics()["reranker_status"], "fallback:RuntimeError")

    def test_urgent_routing(self):
        self.assertTrue(is_urgent("我现在胸口痛、冒冷汗，还有点喘，先上网查查吗？"))
        self.assertTrue(is_urgent("胸口疼还冒冷汗，怎么处理？"))
        self.assertFalse(is_urgent("清淡饮食是不是只要少放盐？"))

    def test_personal_clinical_decisions_are_out_of_scope(self):
        self.assertTrue(needs_clinical_decision("我的降压药能停掉吗？"))
        self.assertTrue(needs_clinical_decision("请根据我的胸部 CT 影像判断是不是肺癌。"))
        self.assertFalse(needs_clinical_decision("高血压平时怎么自己管理？"))

if __name__ == "__main__":
    unittest.main()
