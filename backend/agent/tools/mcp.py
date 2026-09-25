"""从现有 MCP 服务装载工具

复用 mcp-serve 已实现的天气/新闻/用户数据工具，不在 LangGraph 侧重写一遍。
"""

import logging
from typing import List

from core.runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)


async def load_mcp_tools() -> List:
    """连接失败返回空列表：对话可以继续，只是这一轮没有外部工具"""
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(
            {"aide": {"transport": "streamable_http", "url": RuntimeConfig.MCP_SERVER_URL}},
            # 服务端工具名已自带 weather_ / news_ / user_data_ 前缀，再加服务前缀就啰嗦了
            tool_name_prefix=False,
        )
        tools = await client.get_tools()
        logger.info(f"MCP 工具加载完成：{len(tools)} 个")
        return tools
    except Exception as e:
        logger.warning(f"MCP 工具加载失败，本轮以纯对话模式运行: {e}")
        return []
