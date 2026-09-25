"""LangGraph 流事件 → WebSocket 协议

单独成模块的原因：websocket_api.py 里混着连接管理、DB 写入和并发队列，把协议映射抽
出来才能离线测试。

两种帧：
- 过程帧（delta / node_update / tool_call / tool_output / tools_list）载荷很小，
  旧引擎每个 token 下发一整份 ChatResponse，raw_response 越攒越长，一帧比一帧大；
- 收尾的 completion 帧沿用 ChatResponse 形状，前端读取历史与面板的方式不用改。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel

from core.web_socket_core import MessageType, WebSocketMessage

AGENT_NAME = "Aide"
AGENT_DESCRIPTION = "LangGraph 单代理 + 工具图（自研 RAG 笔记 + MCP 外部数据）"
GUARDRAIL_NAMES = ["Safety Guardrail", "Relevance Guardrail"]


def agents_meta(tools_manifest: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """单代理的元信息

    handoffs 恒为空（6 代理 handoff 已被单 agent + 工具图取代），input_guardrails 要
    带上：前端"安全护栏"分区按它判断当前代理挂了哪些护栏。
    """
    return [{
        "name": AGENT_NAME,
        "description": AGENT_DESCRIPTION,
        "handoffs": [],
        "tools": [tool.get("name", "") for tool in tools_manifest or []],
        "input_guardrails": GUARDRAIL_NAMES,
    }]


class MessageResponse(BaseModel):
    content: str
    agent: str


class AgentEvent(BaseModel):
    id: str
    type: str
    agent: str
    content: str
    metadata: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None


class GuardrailCheck(BaseModel):
    id: str
    name: str
    input: str
    reasoning: str
    passed: bool
    timestamp: float


class ChatResponse(BaseModel):
    conversation_id: str
    current_agent: str
    messages: List[MessageResponse]
    events: List[AgentEvent]
    context: Dict[str, Any]
    agents: List[Dict[str, Any]]
    raw_response: str
    tools: List[Dict[str, Any]] = []
    guardrails: List[GuardrailCheck] = []
    is_finished: bool = False
    is_error: bool = False
    error_message: str = ""


class WsStreamTranslator:
    """一轮对话一个实例：累积已流出的文本，并把事件翻译成待下发的消息"""

    def __init__(self, *, user_id: str, connection_id: str, conversation_id: str,
                 context: Optional[Dict[str, Any]] = None,
                 tools_manifest: Optional[List[Dict[str, Any]]] = None):
        self.user_id = str(user_id)
        self.connection_id = connection_id
        self.conversation_id = conversation_id
        self.context = context or {}
        self.tools_manifest = tools_manifest or []
        self.text_so_far = ""

    @property
    def room_id(self) -> str:
        return f"user_{self.user_id}_room"

    def _message(self, content: Dict[str, Any]) -> WebSocketMessage:
        return WebSocketMessage(
            type=MessageType.AI_RESPONSE,
            content=content,
            sender_id="system",
            receiver_id=None,
            room_id=self.room_id,
        )

    def tools_list_message(self) -> WebSocketMessage:
        """开场告诉前端这张图上有谁、能用哪些工具

        顺带把 conversation_id 带回去：新会话的 ID 是服务端生成的，过程帧里若不带，
        前端要到 completion 才知道，中途刷新或切换就会接不上同一线程。
        """
        return self._message({
            "type": "tools_list",
            "conversation_id": self.conversation_id,
            "agents": agents_meta(self.tools_manifest),
            "tools": self.tools_manifest,
        })

    async def feed(self, event: Dict[str, Any]) -> Optional[WebSocketMessage]:
        kind = event.get("kind")

        if kind == "delta":
            text = event.get("text", "")
            self.text_so_far += text
            return self._message({"type": "delta", "delta": text,
                                  "text_so_far": self.text_so_far,
                                  "node": event.get("node", "")})
        if kind == "node_update":
            return self._message({"type": "node_update", "node": event.get("node", ""),
                                  "status": event.get("status", "")})
        if kind == "tool_call":
            return self._message({"type": "tool_call", "tool": event.get("name", ""),
                                  "arguments": event.get("arguments") or {},
                                  "tool_call_id": event.get("tool_call_id", "")})
        if kind == "tool_output":
            return self._message({"type": "tool_output", "tool": event.get("name", ""),
                                  "summary": event.get("summary", ""),
                                  "tool_call_id": event.get("tool_call_id", "")})
        return None

    def build_chat_response(self, answer) -> ChatResponse:
        """answer 是 agent.runtime.AideAnswer"""
        text = answer.text or ""
        author = "Guardrails" if answer.blocked else AGENT_NAME
        now = datetime.now().timestamp()

        events = [
            AgentEvent(
                id=uuid4().hex,
                type=item.get("type", "tool_call"),
                agent=AGENT_NAME,
                content=str(item.get("content", "")),
                metadata={"tool": item.get("tool", ""),
                          "arguments": item.get("arguments", {}),
                          "tool_call_id": item.get("tool_call_id", "")},
                timestamp=now,
            )
            for item in (answer.tool_events or [])
        ]
        guardrails = [
            GuardrailCheck(
                id=f"guardrail-{index}",
                name=str(check.get("name", "Guardrail")),
                input=str(check.get("input", "")),
                reasoning=str(check.get("reasoning", "")),
                passed=bool(check.get("passed")),
                timestamp=now,
            )
            for index, check in enumerate(answer.guardrail_checks or [])
        ]

        return ChatResponse(
            conversation_id=self.conversation_id,
            current_agent=AGENT_NAME,
            messages=[MessageResponse(content=text, agent=author)] if text else [],
            events=events,
            context=self.context,
            agents=agents_meta(self.tools_manifest),
            tools=self.tools_manifest,
            raw_response=text,
            guardrails=guardrails,
            is_finished=True,
            is_error=bool(answer.error),
            error_message=answer.error or "",
        )

    def completion_message(self, answer) -> WebSocketMessage:
        note = ("输入被护栏拦截" if answer.blocked
                else "处理过程中发生错误" if answer.error
                else "对话完成")
        return self._message({
            "type": "completion",
            "final_response": self.build_chat_response(answer).model_dump(),
            "message": note,
        })
