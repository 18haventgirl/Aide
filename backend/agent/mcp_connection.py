"""Keep task-affine MCP stream contexts alive independently of browser sessions."""
import asyncio
import logging

log = logging.getLogger(__name__)


class MCPConnectionOwner:
    def __init__(self, factory, attempts=30, interval=2.0):
        self.factory, self.attempts, self.interval = factory, attempts, interval
        self.server = None
        self.task = None
        self.ready = None
        self.stop_event = None

    async def start(self):
        if self.task is None:
            self.ready = asyncio.get_running_loop().create_future()
            self.stop_event = asyncio.Event()
            self.task = asyncio.create_task(self._run(), name="aide-mcp-connection-owner")
        return await asyncio.shield(self.ready)

    async def _cleanup(self):
        if self.server is not None:
            try:
                await self.server.cleanup()
            except Exception as exc:
                log.warning("MCP cleanup failed: %s", type(exc).__name__)

    async def _run(self):
        try:
            for attempt in range(self.attempts):
                try:
                    self.server = self.factory()
                    await self.server.connect()
                    self.ready.set_result(True)
                    await self.stop_event.wait()
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("MCP connection attempt failed: %s", type(exc).__name__)
                    await self._cleanup()
                    self.server = None
                    if attempt + 1 < self.attempts:
                        await asyncio.sleep(self.interval)
            self.ready.set_result(False)
        finally:
            if not self.ready.done():
                self.ready.set_result(False)
            await self._cleanup()

    async def close(self):
        if self.task is not None:
            self.stop_event.set()
            if not self.task.done() and not self.ready.done():
                self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
