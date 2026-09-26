"""图状态

在 LangChain 的 AgentState（messages / jump_to / structured_response）上加一个自有字段。
retrieved 存纯 dict 而不是 Document：checkpoint 序列化更省事，也方便直接下发给前端。
"""

from typing import Any, Dict, List

from langchain.agents import AgentState


class AideState(AgentState):
    retrieved: List[Dict[str, Any]]
