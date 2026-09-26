"""健康检查端点

每一项都做真实探测，但"空闲"不是故障：最后一个 WebSocket 连接断开时心跳任务会被取消，
如果据此判 websocket 不健康，服务就会在没人聊天的时候报 degraded（实测：e2e 跑完、
浏览器一关，/api/health 立刻变 degraded，而对话功能完全正常）。
"""

import asyncio
from types import SimpleNamespace

import api.system_api as system_api
from api.system_api import health_check


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, _statement):
        return SimpleNamespace()


class _Engine:
    def connect(self):
        return _Connection()


def _probe(monkeypatch, *, connections=(), heartbeat=True, db=True, vector="healthy"):
    monkeypatch.setattr(system_api.service_manager, "get_db_client",
                        lambda: SimpleNamespace(engine=_Engine() if db else None))
    monkeypatch.setattr("core.retrieval.store.vector_health",
                        lambda: {"status": vector} if vector == "healthy"
                        else {"status": "unhealthy", "error": "chroma 目录被占用"})
    monkeypatch.setattr(system_api, "connection_manager", SimpleNamespace(
        active_connections=list(connections),
        heartbeat_task=object() if heartbeat else None))

    return asyncio.run(health_check())


def test_idle_server_is_healthy(monkeypatch):
    payload = _probe(monkeypatch, connections=(), heartbeat=False)

    assert payload["services"]["websocket"] == "healthy"
    assert payload["status"] == "healthy"
    assert payload["active_connections"] == 0


def test_live_connection_without_heartbeat_is_not_healthy(monkeypatch):
    """有连接却没有心跳任务才是真故障：那个连接不会被清理也不会被探测"""
    payload = _probe(monkeypatch, connections=["c1"], heartbeat=False)

    assert payload["services"]["websocket"] == "unhealthy"
    assert payload["status"] == "degraded"


def test_dead_database_is_unhealthy(monkeypatch):
    payload = _probe(monkeypatch, db=False)

    assert payload["services"]["database"] == "unhealthy"
    assert payload["status"] == "unhealthy"


def test_vector_failure_degrades_but_does_not_fail_the_service(monkeypatch):
    """笔记检索挂了，对话仍然可用（模型只是拿不到命中），所以算 degraded 不算 unhealthy"""
    payload = _probe(monkeypatch, vector="unhealthy")

    assert payload["services"]["vector_database"] == "unhealthy"
    assert payload["status"] == "degraded"
