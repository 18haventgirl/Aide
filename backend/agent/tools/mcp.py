"""MCP 工具装载：官方适配器 langchain-mcp-adapters

服务端与客户端共用一套依赖约束（fastmcp 3.4.7 + mcp 1.x，见 requirements.txt 开头）。
工具调用时适配器自己开会话、用完关，所以进程里不需要长期持有的 MCP 连接。

tool_name_prefix=False：服务端工具名已自带 weather_ / news_ / recipe_ / user_data_ 前缀，
再加一层服务名前缀只会让名字变长、并与前端工具清单对不上。
"""

import logging
from typing import Any, List, Optional

from langchain_mcp_adapters.client import MultiServerMCPClient

from core.runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)

SERVER_KEY = "aide"


async def load_mcp_tools(url: Optional[str] = None) -> List[Any]:
    """取一次工具清单。连不上返回空列表：对话继续，只是这一轮没有外部工具"""
    client = MultiServerMCPClient(
        {SERVER_KEY: {"transport": "streamable_http",
                      "url": url or RuntimeConfig.MCP_SERVER_URL}},
        tool_name_prefix=False,
    )
    try:
        tools = await client.get_tools()
    except Exception as exc:
        logger.warning(f"MCP 工具加载失败，本轮以纯对话模式运行: {exc}")
        return []

    logger.info(f"MCP 工具加载完成：{len(tools)} 个")
    return tools
