"""MCP 工具装载走官方适配器

三条约束：连不上要降级成空列表（对话照常，只是这一轮没有外部工具）、工具名不能再被加上
服务名前缀（服务端名字已自带 weather_/news_/recipe_/user_data_，加前缀会和前端清单不一致）、
连接配置只从 RuntimeConfig 来（换端口不能改代码）。
"""

import asyncio
from types import SimpleNamespace

import agent.tools.mcp as mcp_mod
from agent.tools.mcp import load_mcp_tools
from core.runtime_config import RuntimeConfig


def _spy(returned=None, raises=None):
    """替身适配器：记录构造参数，按脚本返回工具或抛错"""
    captured = {}

    class Spy:
        def __init__(self, servers, **kwargs):
            captured["servers"] = servers
            captured.update(kwargs)

        async def get_tools(self):
            if raises is not None:
                raise raises
            return returned or []

    return Spy, captured


def test_load_returns_the_adapters_tools(monkeypatch):
    fake = [SimpleNamespace(name="weather_get_current_weather"),
            SimpleNamespace(name="user_data_get_todos")]
    Spy, _ = _spy(returned=fake)
    monkeypatch.setattr(mcp_mod, "MultiServerMCPClient", Spy)

    tools = asyncio.run(load_mcp_tools())

    assert [t.name for t in tools] == ["weather_get_current_weather", "user_data_get_todos"]


def test_connection_failure_degrades_to_empty(monkeypatch):
    Spy, _ = _spy(raises=OSError("connection refused"))
    monkeypatch.setattr(mcp_mod, "MultiServerMCPClient", Spy)

    assert asyncio.run(load_mcp_tools()) == []


def test_tool_name_prefix_is_disabled(monkeypatch):
    Spy, captured = _spy()
    monkeypatch.setattr(mcp_mod, "MultiServerMCPClient", Spy)

    asyncio.run(load_mcp_tools())

    assert captured["tool_name_prefix"] is False


def test_connection_comes_from_runtime_config(monkeypatch):
    Spy, captured = _spy()
    monkeypatch.setattr(mcp_mod, "MultiServerMCPClient", Spy)

    asyncio.run(load_mcp_tools())

    assert captured["servers"] == {
        "aide": {"transport": "streamable_http", "url": RuntimeConfig.MCP_SERVER_URL}}


def test_url_can_be_overridden_for_tests(monkeypatch):
    Spy, captured = _spy()
    monkeypatch.setattr(mcp_mod, "MultiServerMCPClient", Spy)

    asyncio.run(load_mcp_tools(url="http://127.0.0.1:9999/mcp"))

    assert captured["servers"]["aide"]["url"] == "http://127.0.0.1:9999/mcp"
