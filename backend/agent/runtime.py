"""LangGraph 运行时：业务层访问编排引擎的唯一入口

WebSocket 层只管收发，不关心里面是 LangGraph 还是别的；ask() 把图跑完的一次问答
整理成 AideAnswer，流式路径后面接在同一张图上。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.context import UserContext, build_user_context

logger = logging.getLogger(__name__)

TOOL_OUTPUT_CHARS = 500


@dataclass
class AideAnswer:
    text: str = ""
    tool_events: List[Dict[str, Any]] = field(default_factory=list)
    guardrail_checks: List[Dict[str, Any]] = field(default_factory=list)
    blocked: bool = False
    error: Optional[str] = None


class AideRuntime:
    """持有编译好的图；模型与 MCP 都可用时才构建，之后复用"""

    def __init__(self):
        self._agent: Any = None
        self._has_memory: bool = False

    async def ensure_ready(self) -> None:
        """懒构建。模型不可用时抛 RuntimeError，由上层转成可读错误。"""
        if self._agent is not None:
            return

        from agent.graph import build_agent, default_tools
        from agent.model import build_chat_model
        from agent.tools.mcp import load_mcp_tools

        model = build_chat_model()
        if model is None:
            raise RuntimeError("未配置可用的对话模型（检查 OPENAI_API_KEY / OPENAI_API_BASE_URL）")

        mcp_tools = await load_mcp_tools()
        tools = [*default_tools(), *mcp_tools]
        self._agent = await build_agent(model, tools=tools)
        self._has_memory = False      # 阶段 2 接上 checkpointer 后置 True
        logger.info(f"Aide 运行时就绪：{len(tools)} 个工具")

    async def _state_len(self, config: Dict[str, Any]) -> int:
        """本轮之前的消息条数，用来把历史排除在本次结果外"""
        try:
            snapshot = await self._agent.aget_state(config)
        except Exception as exc:
            logger.debug(f"读取线程状态失败，按无历史处理: {exc}")
            return 0
        values = getattr(snapshot, "values", None) or {}
        return len(values.get("messages") or [])

    async def ask(self, user_id: int, conversation_id: str, text: str,
                  user_name: str = "", lat: str = "", lng: str = "",
                  city: str = "") -> AideAnswer:
        """跑一轮对话（非流式）"""
        try:
            await self.ensure_ready()
        except Exception as exc:
            logger.warning(f"运行时不可用: {exc}")
            return AideAnswer(error=str(exc))

        context: Optional[UserContext] = None
        try:
            context = build_user_context(user_id, user_name=user_name, lat=lat, lng=lng, city=city)
            config = {"configurable": {"thread_id": conversation_id}, "recursion_limit": 25}
            before = await self._state_len(config) if self._has_memory else 0
            state = await self._agent.ainvoke(
                {"messages": [HumanMessage(content=text)]}, config=config, context=context
            )
        except Exception as exc:
            logger.exception("图执行失败")
            checks = context.guardrail_checks if context else []
            return AideAnswer(error=str(exc), guardrail_checks=checks)

        messages = (state.get("messages") if isinstance(state, dict) else None) or []
        answer, events, blocked = _read_outcome(messages[before:])
        checks = context.guardrail_checks if context else []
        return AideAnswer(text=answer, tool_events=events,
                          guardrail_checks=checks, blocked=blocked)


def _read_outcome(messages: List[Any]) -> tuple:
    """把本轮新增消息拆成 (回答, 工具事件, 是否被拦)

    工具调用与结果分属两条消息，按 tool_call_id 配好对再上报，前端一行就能显示
    "哪个工具 + 什么参数 + 返回了什么"。
    """
    answer, events, blocked = "", [], False
    pending: Dict[str, Dict[str, Any]] = {}

    for message in messages:
        if isinstance(message, ToolMessage):
            call = pending.get(message.tool_call_id, {})
            events.append({
                "type": "tool_output",
                "content": str(message.content)[:TOOL_OUTPUT_CHARS],
                "tool": message.name or call.get("tool", ""),
                "arguments": call.get("arguments", {}),
                "tool_call_id": message.tool_call_id,
            })
            continue

        if not isinstance(message, AIMessage):
            continue

        for call in (message.tool_calls or []):
            entry = {"tool": call.get("name", ""), "arguments": call.get("args") or {}}
            pending[call.get("id", "")] = entry
            events.append({"type": "tool_call", "content": entry["tool"], **entry,
                           "tool_call_id": call.get("id", "")})

        content = str(message.content or "").strip()
        if not content:
            continue
        answer = content
        if getattr(message, "name", None) == "Guardrails":
            blocked = True

    return answer, events, blocked


aide_runtime = AideRuntime()
