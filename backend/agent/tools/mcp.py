"""MCP 工具桥接

不用 langchain-mcp-adapters：它钉住 mcp<2，而本仓库的 MCP 服务端跑在 fastmcp 4（要求
mcp>=2）。同环境同装时 pip 会把 mcp 降到 1.30，服务端子进程启动即 ModuleNotFoundError:
mcp.server.request_state，表现为"后端正常但没有外部工具"。这里直接用 mcp 官方客户端，
自己把工具包成 LangChain StructuredTool，服务端与客户端共用一套 mcp 版本。
"""

import logging
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Literal, Optional, Tuple

from langchain_core.tools import StructuredTool
from mcp import Client
from pydantic import Field, create_model

from core.runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)

_JSON_TYPES = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _model_name(raw: str) -> str:
    return "".join(part if part.isidentifier() else "_" for part in raw) + "Args"


def args_model_from_schema(name: str, schema: Optional[Dict[str, Any]]) -> type:
    """按 MCP 工具的 JSON Schema 生成 pydantic 参数模型

    required 决定必填；enum 收成 Literal，让非法取值在调用前就被挡下；类型不认识时
    退成 Any，宁可放行也别让某个工具的怪类型拖垮整批工具。
    """
    properties = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])

    fields: Dict[str, Tuple[Any, Any]] = {}
    for key, spec in properties.items():
        spec = spec or {}
        enum = spec.get("enum")
        py_type = _JSON_TYPES.get(spec.get("type"), Any)
        if enum:
            py_type = Literal[tuple(enum)]
        description = (spec.get("description") or "").strip()

        if key in required:
            fields[key] = (py_type, Field(required=True, description=description))
        else:
            default = spec.get("default", "" if py_type is str else None)
            fields[key] = (Optional[py_type], Field(default=default, description=description))

    return create_model(_model_name(name), **fields)


def _text_of(result: Any) -> str:
    """把 CallToolResult 收成纯文本

    正常返回是 [{"type":"text","text":...}] 分片列表，直接 str() 会把 Python repr
    灌给模型；is_error 也要留下可见痕迹，否则模型以为调用成功。
    """
    parts = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
        elif isinstance(item, str):
            parts.append(item)
    body = "\n".join(parts) or str(getattr(result, "structured_content", None) or "")
    if getattr(result, "is_error", False):
        return f"工具报错：{body or '未知错误'}"
    return body


class MCPBridge:
    """一条长开的 MCP 客户端连接；工具清单在 open() 时取一次，调用都走同一个会话"""

    def __init__(self, url: str):
        self.url = url
        self.tools: List[StructuredTool] = []
        self._stack: Optional[AsyncExitStack] = None
        self._client: Any = None

    async def __aenter__(self) -> "MCPBridge":
        await self.open()
        return self

    async def __aexit__(self, *exc_info) -> bool:
        await self.close()
        return False

    async def open(self) -> int:
        stack = AsyncExitStack()
        try:
            client = await stack.enter_async_context(Client(self.url))
            listed = await client.list_tools()
        except Exception:
            await stack.aclose()
            raise

        self._stack = stack
        self._client = client
        self.tools = [self._wrap(spec) for spec in listed.tools]
        return len(self.tools)

    async def close(self) -> None:
        stack, self._stack = self._stack, None
        self._client = None
        self.tools = []
        if stack is not None:
            await stack.aclose()

    async def _call(self, name: str, arguments: Dict[str, Any]) -> str:
        try:
            result = await self._client.call_tool(name, arguments)
        except Exception as exc:
            logger.warning(f"MCP 工具 {name} 调用失败: {exc}")
            return f"工具 {name} 调用失败：{exc}"
        return _text_of(result)

    def _wrap(self, spec: Any) -> StructuredTool:
        schema = getattr(spec, "input_schema", None)
        bridge = self

        async def invoke(**kwargs) -> str:
            return await bridge._call(spec.name, kwargs)

        return StructuredTool.from_function(
            name=spec.name,
            description=(getattr(spec, "description", None) or spec.name).strip(),
            coroutine=invoke,
            args_schema=args_model_from_schema(spec.name, schema),
            handle_tool_error=True,
        )


async def build_mcp_bridge(url: Optional[str] = None) -> Optional[MCPBridge]:
    """连不上返回 None：对话可以继续，只是这一轮没有外部工具"""
    bridge = MCPBridge(url or RuntimeConfig.MCP_SERVER_URL)
    try:
        count = await bridge.open()
    except Exception as exc:
        logger.warning(f"MCP 工具加载失败，本轮以纯对话模式运行: {exc}")
        await bridge.close()
        return None

    logger.info(f"MCP 工具加载完成：{count} 个")
    return bridge
