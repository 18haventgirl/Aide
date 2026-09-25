"""MCP 工具桥接

不用 langchain-mcp-adapters：它钉住 mcp<2，而本仓库的 MCP 服务端跑在 fastmcp 4（要求
mcp>=2）。同环境同装时 pip 会把 mcp 降到 1.30，服务端子进程启动即报
ModuleNotFoundError: mcp.server.request_state —— 症状是"后端起来了但没有外部工具"。
所以这里直接用 mcp 官方客户端，自己把工具包成 StructuredTool。

测试全部离线：用假 Client 替身，不依赖 8102 在跑。
"""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent.tools import mcp as mcp_mod
from agent.tools.mcp import MCPBridge, args_model_from_schema, build_mcp_bridge

WEATHER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "latitude": {"type": "number", "description": "纬度"},
        "longitude": {"type": "number", "description": "经度"},
        "unit": {"type": "string", "enum": ["celsius", "fahrenheit"], "default": "celsius"},
        "days": {"type": "integer", "default": 3},
    },
    "required": ["latitude", "longitude"],
}


def _spec(name="weather_get_current_weather", description="查当前天气", schema=None):
    return SimpleNamespace(name=name, description=description,
                           input_schema=schema if schema is not None else WEATHER_SCHEMA)


class FakeClient:
    """假 mcp.Client：可当异步上下文管理器，记录调用"""

    instances = []

    def __init__(self, url, **kwargs):
        self.url = url
        self.calls = []
        self.tools = [_spec()]
        self.result = SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"temp": 23.3}')], is_error=False)
        FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_tools(self):
        return SimpleNamespace(tools=self.tools)

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        return self.result


def test_required_and_optional_args_are_distinguished():
    model = args_model_from_schema("weather", WEATHER_SCHEMA)

    ok = model(latitude=31.2, longitude=121.4)
    assert (ok.latitude, ok.longitude, ok.unit, ok.days) == (31.2, 121.4, "celsius", 3)
    with pytest.raises(ValidationError):
        model(latitude=31.2)


def test_enum_becomes_a_validated_literal():
    model = args_model_from_schema("weather", WEATHER_SCHEMA)
    assert model(latitude=1.0, longitude=2.0, unit="fahrenheit").unit == "fahrenheit"
    with pytest.raises(ValidationError):
        model(latitude=1.0, longitude=2.0, unit="kelvin")


def test_unknown_or_empty_schema_still_builds_a_model():
    model = args_model_from_schema("odd", {"properties": {"payload": {"type": "weird"}}})
    assert model(payload={"a": 1}).payload == {"a": 1}
    assert args_model_from_schema("bare", None).model_fields == {}


def test_bridge_wraps_specs_as_langchain_tools():
    bridge = MCPBridge("http://example.invalid/mcp")
    bridge._client = FakeClient("http://example.invalid/mcp")

    tool = bridge._wrap(_spec(description="查当前天气\n多行说明"))
    assert tool.name == "weather_get_current_weather"
    assert tool.description.startswith("查当前天气")     # 完整说明留给模型
    assert "多行说明" in tool.description
    assert set(tool.args.keys()) == {"latitude", "longitude", "unit", "days"}

    out = asyncio.run(tool.ainvoke({"latitude": 31.2, "longitude": 121.4}))
    assert out == '{"temp": 23.3}'
    assert bridge._client.calls == [("weather_get_current_weather",
                                     {"latitude": 31.2, "longitude": 121.4,
                                      "unit": "celsius", "days": 3})]

    with pytest.raises(Exception):        # 少必填参数 → 调用前就被 schema 挡下
        asyncio.run(tool.ainvoke({"longitude": 121.4}))


def test_text_parts_are_joined_and_errors_stay_visible():
    bridge = MCPBridge("http://example.invalid/mcp")
    bridge._client = FakeClient("http://example.invalid/mcp")
    bridge._client.result = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="第一段"),
                 SimpleNamespace(type="text", text="第二段")], is_error=False)
    tool = bridge._wrap(_spec())
    assert asyncio.run(tool.ainvoke({"latitude": 1, "longitude": 2})) == "第一段\n第二段"

    bridge._client.result = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="用户 9 不存在")], is_error=True)
    out = asyncio.run(tool.ainvoke({"latitude": 1, "longitude": 2}))
    assert out.startswith("工具报错") and "用户 9 不存在" in out


def test_open_populates_tools_and_close_is_repeatable(monkeypatch):
    monkeypatch.setattr(mcp_mod, "Client", FakeClient)
    bridge = MCPBridge("http://127.0.0.1:8102/mcp")

    count = asyncio.run(bridge.open())
    assert count == 1 and bridge.tools[0].name == "weather_get_current_weather"
    asyncio.run(bridge.close())
    asyncio.run(bridge.close())          # 幂等，不炸


def test_call_failure_becomes_a_string_for_the_model(monkeypatch):
    class BrokenClient(FakeClient):
        async def call_tool(self, name, arguments=None):
            raise RuntimeError("connection closed")

    monkeypatch.setattr(mcp_mod, "Client", FakeClient)
    bridge = MCPBridge("http://example.invalid/mcp")
    bridge._client = BrokenClient("http://example.invalid/mcp")
    tool = bridge._wrap(_spec())

    out = asyncio.run(tool.ainvoke({"latitude": 1, "longitude": 2}))
    assert isinstance(out, str) and "connection closed" in out


def test_build_mcp_bridge_returns_none_when_the_server_is_unreachable(monkeypatch):
    class Unreachable(FakeClient):
        def __init__(self, url, **kwargs):
            raise OSError("connection refused")

    monkeypatch.setattr(mcp_mod, "Client", Unreachable)
    assert asyncio.run(build_mcp_bridge("http://127.0.0.1:1/mcp")) is None


def test_build_mcp_bridge_uses_the_configured_url(monkeypatch):
    monkeypatch.setattr(mcp_mod, "Client", FakeClient)
    bridge = asyncio.run(build_mcp_bridge("http://127.0.0.1:8102/mcp"))

    assert bridge is not None and len(bridge.tools) == 1
    assert FakeClient.instances[-1].url == "http://127.0.0.1:8102/mcp"
