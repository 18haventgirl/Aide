import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from medical import runtime


class MedicalRuntimeTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
