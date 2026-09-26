"""单 agent + 工具图

取代原来的 6 代理 handoff 结构：一个 Aide agent 挂全部工具（MCP 外部数据 + 本地 RAG
笔记），护栏与身份覆写走 middleware，多轮状态交给 checkpointer。
"""

import logging
from typing import Any, List, Optional, Sequence

from langchain.agents import create_agent

from agent.context import UserContext
from agent.middleware import build_guardrail_middlewares, build_identity_middleware
from agent.state import AideState

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是 LG-Aide，个人日常助手。可用能力：天气与预报、菜谱、新闻、待办与笔记。\n"
    "规则：\n"
    "1) 需要外部信息或读写用户数据时调用工具，不要凭空编造。\n"
    "2) 用户身份由系统提供，不要追问 user_id。\n"
    "3) 带 [笔记检索结果] 的系统消息是用户自己笔记的命中片段，可用，但需说明来源是笔记。\n"
    "4) 回答简洁，中文优先，先结论后依据。\n"
    "5) 工具报错要如实说明。\n"
    "6) 调用工具前不要输出“我来帮你查一下”这类过程说明——字会流到用户屏幕上，"
    "却在最终回答里消失。"
)


def default_tools() -> List[Any]:
    """MCP 不可用时的兜底工具集：笔记检索与新建"""
    from agent.tools.notes import save_note, search_my_notes

    return [search_my_notes, save_note]


async def build_agent(model,
                      tools: Optional[Sequence[Any]] = None,
                      checkpointer: Any = None,
                      extra_middleware: Sequence[Any] = ()) -> Any:
    """构图。model 缺失时抛 ValueError，由调用方转成可读错误。

    tools=None 表示"用默认工具集"（笔记工具）；显式传 [] 才是真的不给工具。
    """
    if model is None:
        raise ValueError("未配置可用的对话模型（检查 OPENAI_API_KEY / OPENAI_API_BASE_URL）")

    from agent.retrieval import build_retrieval_injector, build_retrieval_middleware

    tool_list: List[Any] = list(tools) if tools is not None else default_tools()
    middleware = [
        build_retrieval_middleware(),          # 每轮先召回笔记
        build_retrieval_injector(),
        build_identity_middleware(),
        *build_guardrail_middlewares(model),
        *extra_middleware,
    ]
    agent = create_agent(
        model=model,
        tools=tool_list,
        system_prompt=SYSTEM_PROMPT,
        middleware=middleware,
        state_schema=AideState,
        context_schema=UserContext,
        checkpointer=checkpointer,
        name="Aide",
    )
    logger.info(f"Aide 图已构建：{len(tool_list)} 个工具，{len(middleware)} 个中间件")
    return agent
