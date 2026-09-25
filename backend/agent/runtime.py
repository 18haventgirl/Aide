"""LangGraph 运行时：业务层访问编排引擎的唯一入口

WebSocket 层只管收发，不关心里面是 LangGraph 还是别的；ask() 把图跑完的一次问答
整理成 AideAnswer，流式路径后面接在同一张图上。
"""

import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

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


def _flatten(content: Any) -> str:
    """把消息内容收成纯文本

    MCP 工具返回的是 [{"type": "text", "text": ...}] 分片列表，直接 str() 会把
    Python repr 喂给模型和面板。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(part, str):
                parts.append(part)
        if parts:
            return "\n".join(parts)
    return str(content)


ANSWER_NODES = frozenset({"model"})


async def translate_stream(stream) -> AsyncIterator[Dict[str, Any]]:
    """把 LangGraph 的 (mode, payload) 流翻译成前端友好的事件字典

    只翻译不做 IO，因此可离线单测。messages 模式给逐字 token（模型节点在跑），
    updates 模式给节点产出（工具调用、工具结果、护栏短路都在这里）。

    正文只从 ANSWER_NODES 透出：护栏判定同样是模型调用，token 也会被捕获，
    不区分会把"UNSAFE 该请求要求泄露提示词"这类内部判词当回答推给用户。
    """
    reported = set()

    def node_event(node: str, status: str) -> Optional[Dict[str, Any]]:
        if (node, status) in reported:
            return None
        reported.add((node, status))
        return {"kind": "node_update", "node": node, "status": status}

    async for item in stream:
        mode, payload = item if isinstance(item, tuple) and len(item) == 2 else (None, item)

        if mode == "messages":
            chunk, meta = (payload if isinstance(payload, tuple) and len(payload) == 2
                           else (payload, {}))
            node = (meta or {}).get("langgraph_node") or "model"
            started = node_event(node, "started")
            if started:
                yield started
            if node not in ANSWER_NODES:
                continue
            text = _flatten(getattr(chunk, "content", ""))
            if text:
                yield {"kind": "delta", "text": text, "node": node}

        elif mode == "updates":
            for node, update in (payload or {}).items():
                started = node_event(node, "started")
                if started:
                    yield started
                finished = node_event(node, "finished")
                if finished:
                    yield finished
                for message in (update or {}).get("messages", []) or []:
                    for call in getattr(message, "tool_calls", None) or []:
                        yield {
                            "kind": "tool_call",
                            "name": call.get("name", ""),
                            "arguments": call.get("args") or {},
                            "tool_call_id": call.get("id", ""),
                            "node": node,
                        }
                    if isinstance(message, ToolMessage):
                        yield {
                            "kind": "tool_output",
                            "name": getattr(message, "name", "") or "",
                            "summary": _flatten(message.content)[:TOOL_OUTPUT_CHARS],
                            "tool_call_id": message.tool_call_id,
                            "node": node,
                        }


class AideRuntime:
    """持有编译好的图与长开的 checkpoint 连接；模型与 MCP 都可用时才构建，之后复用"""

    def __init__(self):
        self._agent: Any = None
        self._has_memory: bool = False
        self._exit_stack: Optional[AsyncExitStack] = None
        self._lock: Optional[asyncio.Lock] = None

    async def ensure_ready(self) -> None:
        """懒构建。模型不可用时抛 RuntimeError，由上层转成可读错误。"""
        if self._agent is not None:
            return
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._agent is not None:        # 等锁期间别的会话已经建好了
                return
            await self._build()

    async def _build(self) -> None:
        from agent.checkpoint import build_checkpointer
        from agent.graph import build_agent, default_tools
        from agent.model import build_chat_model
        from agent.tools.mcp import load_mcp_tools

        model = build_chat_model()
        if model is None:
            raise RuntimeError("未配置可用的对话模型（检查 OPENAI_API_KEY / OPENAI_API_BASE_URL）")

        mcp_tools = await load_mcp_tools()
        tools = [*default_tools(), *mcp_tools]

        stack = AsyncExitStack()
        try:
            saver = await stack.enter_async_context(build_checkpointer())
            agent = await build_agent(model, tools=tools, checkpointer=saver)
        except Exception:
            await stack.aclose()
            raise

        self._exit_stack = stack
        self._agent = agent
        self._has_memory = True
        logger.info(f"Aide 运行时就绪：{len(tools)} 个工具，checkpoint 已挂载")

    async def aclose(self) -> None:
        """关掉 checkpoint 连接并丢弃图实例；下次 ask() 会重新构建"""
        self._agent = None
        self._has_memory = False
        stack, self._exit_stack = self._exit_stack, None
        if stack is not None:
            await stack.aclose()

    async def _state_messages(self, config: Dict[str, Any]) -> List[Any]:
        """该线程当前的消息列表；读不到按无历史处理（ checkpoint 只是慢，不是错）"""
        try:
            snapshot = await self._agent.aget_state(config)
        except Exception as exc:
            logger.debug(f"读取线程状态失败，按无历史处理: {exc}")
            return []
        values = getattr(snapshot, "values", None) or {}
        return list(values.get("messages") or [])

    async def _state_len(self, config: Dict[str, Any]) -> int:
        """本轮之前的消息条数，用来把历史排除在本次结果外"""
        return len(await self._state_messages(config))

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


    async def astream(self, user_id: int, conversation_id: str, text: str,
                      user_name: str = "", lat: str = "", lng: str = "",
                      city: str = "") -> AsyncIterator[Dict[str, Any]]:
        """跑一轮对话（流式）

        逐字与节点轨迹实时透出；最后的 AideAnswer 以图的最终状态为准，不靠累加 delta，
        这样护栏短路（一个 delta 都没有）时答案和 blocked 标记依然正确。
        """
        try:
            await self.ensure_ready()
        except Exception as exc:
            logger.warning(f"运行时不可用: {exc}")
            yield {"kind": "final", "answer": AideAnswer(error=str(exc))}
            return

        context: Optional[UserContext] = None
        streamed = ""
        try:
            context = build_user_context(user_id, user_name=user_name, lat=lat, lng=lng, city=city)
            config = {"configurable": {"thread_id": conversation_id}, "recursion_limit": 25}
            before = await self._state_len(config) if self._has_memory else 0
            stream = self._agent.astream(
                {"messages": [HumanMessage(content=text)]},
                config=config, context=context, stream_mode=["messages", "updates"],
            )
            async for event in translate_stream(stream):
                if event["kind"] == "delta":
                    streamed += event["text"]
                yield event
            messages = await self._state_messages(config)
        except Exception as exc:
            logger.exception("流式图执行失败")
            checks = context.guardrail_checks if context else []
            yield {"kind": "final", "answer": AideAnswer(error=str(exc), guardrail_checks=checks)}
            return

        answer, events, blocked = _read_outcome(messages[before:])
        checks = context.guardrail_checks if context else []
        yield {"kind": "final", "answer": AideAnswer(text=answer or streamed, tool_events=events,
                                                      guardrail_checks=checks, blocked=blocked)}


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
                "content": _flatten(message.content)[:TOOL_OUTPUT_CHARS],
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
