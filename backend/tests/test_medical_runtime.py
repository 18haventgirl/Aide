import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from medical import runtime
from medical.schema import MedicalHit


class MedicalRuntimeTests(unittest.TestCase):
    def setUp(self):
        runtime.clear_retrieval_cache()

    def test_reopens_runtime_after_external_sync_type_error(self):
        stale = SimpleNamespace(collection=SimpleNamespace(count=lambda: 1))
        stale.search = MagicMock(side_effect=TypeError("stale Chroma cache"))
        fresh = SimpleNamespace(collection=SimpleNamespace(count=lambda: 1))
        fresh.search = MagicMock(return_value=[])

        with patch.object(runtime, "get_knowledge_base", side_effect=[stale, fresh]) as get_kb:
            get_kb.cache_clear = MagicMock()
            self.assertEqual(runtime.search_with_metrics("发热"), [])
            get_kb.cache_clear.assert_called_once_with()
            fresh.search.assert_called_once_with("发热", limit=5)

    def test_repeated_query_uses_privacy_preserving_memory_cache(self):
        hit = MedicalHit(
            chunk_id="A-1", doc_id="A", title="资料A", section_path="主题",
            text="健康资料", source_org="机构", source_url="https://example.org/a",
        )
        kb = SimpleNamespace(collection=SimpleNamespace(count=lambda: 1))
        kb.search = MagicMock(return_value=[hit])
        kb.search_metrics = MagicMock(return_value={"reranker_status": "applied"})
        with patch.object(runtime, "get_knowledge_base", return_value=kb):
            first = runtime.search_with_metrics("同一个问题", limit=5)
            self.assertFalse(runtime.last_search_metrics()["cache_hit"])
            second = runtime.search_with_metrics("  同一个问题  ", limit=5)
            cached_metrics = runtime.last_search_metrics()
        self.assertEqual(first[0].doc_id, "A")
        self.assertEqual(second[0].doc_id, "A")
        kb.search.assert_called_once_with("同一个问题", limit=5)
        self.assertIsNot(first[0], second[0])
        self.assertTrue(cached_metrics["cache_hit"])
        self.assertEqual(cached_metrics["selected_count"], 1)


if __name__ == "__main__":
    unittest.main()
