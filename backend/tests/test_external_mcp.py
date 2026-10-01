"""An externally managed MCP must not be spawned or killed by the API."""
import os
import unittest
from unittest.mock import AsyncMock, patch


class ExternalMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_owner_avoids_duplicate_process(self):
        import main
        with patch.dict(os.environ, {'AIDE_EXTERNAL_MCP': 'true'}), \
             patch.object(main, 'mcp_server_process', None), \
             patch.object(main.asyncio, 'create_subprocess_exec', new_callable=AsyncMock) as spawn:
            self.assertTrue(await main.start_mcp_server())
            await main.stop_mcp_server()
            spawn.assert_not_called()
            self.assertIsNone(main.mcp_server_process)
