"""运行时用户上下文

取代原 PersonalAssistantContext。LangGraph 通过 create_agent(context_schema=UserContext)
注入，工具与中间件用 runtime.context 读取，因此这里保持纯数据、不带业务方法。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


@dataclass
class UserContext:
    user_id: int
    user_name: str = ""
    lat: str = ""
    lng: str = ""
    city: str = ""
    preferences: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # 本轮护栏检查记录，由 runtime 取出后随 completion 下发前端展示
    guardrail_checks: List[Dict[str, Any]] = field(default_factory=list)


def build_user_context(user_id: int, user_name: str = "", lat: str = "",
                       lng: str = "", city: str = "") -> UserContext:
    """装配上下文。偏好加载失败只记日志、按空偏好继续，不阻断对话。"""
    context = UserContext(user_id=user_id, user_name=user_name, lat=lat, lng=lng, city=city)
    try:
        from service.service_manager import service_manager
        from service.services.preference_service import PreferenceService

        preference_service = service_manager.get_service("preference_service", PreferenceService)
        context.preferences = preference_service.get_all_user_preferences(user_id) or {}
    except Exception as exc:
        logger.warning(f"加载用户 {user_id} 偏好失败，按空偏好继续: {exc}")
    return context
