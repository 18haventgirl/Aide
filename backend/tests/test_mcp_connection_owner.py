import asyncio
import unittest
from unittest.mock import patch
from agent.mcp_connection import MCPConnectionOwner
from core.performance_manager import PerformanceManager


class ConnectionOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_and_cleanup_run_in_same_persistent_task(self):
        events = []
        class Client:
            async def connect(self): events.append(("connect", asyncio.current_task()))
            async def cleanup(self): events.append(("cleanup", asyncio.current_task()))
        owner = MCPConnectionOwner(Client, attempts=1)
        self.assertTrue(await owner.start())
        self.assertFalse(owner.task.done())
        await owner.close()
        self.assertIs(events[0][1], events[1][1])
        self.assertIsNot(events[0][1], asyncio.current_task())

    async def test_failed_client_is_cleaned_before_retry(self):
        events, created = [], []
        class Client:
            def __init__(self): self.index = len(created); created.append(self)
            async def connect(self):
                events.append(("connect", self.index, asyncio.current_task()))
                if self.index == 0: raise RuntimeError("injected handshake failure")
            async def cleanup(self): events.append(("cleanup", self.index, asyncio.current_task()))
        owner = MCPConnectionOwner(Client, attempts=2, interval=0)
        self.assertTrue(await owner.start())
        await owner.close()
        self.assertEqual([(kind, index) for kind, index, _ in events], [("connect", 0), ("cleanup", 0), ("connect", 1), ("cleanup", 1)])
        self.assertEqual(len({task for _, _, task in events}), 1)

    async def test_browser_waiter_cancel_does_not_cancel_initialization(self):
        manager = PerformanceManager()
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def initialize_agents():
            calls.append(1); entered.set(); await release.wait()
        with patch("core.performance_manager.service_manager.initialize", return_value=True), patch.object(manager, "_initialize_assistant_manager", initialize_agents):
            first = asyncio.create_task(manager.initialize())
            await entered.wait()
            first.cancel()
            with self.assertRaises(asyncio.CancelledError): await first
            second = asyncio.create_task(manager.initialize())
            release.set()
            self.assertTrue(await second)
            self.assertEqual(len(calls), 1)
        await manager.aclose()


if __name__ == "__main__": unittest.main()
