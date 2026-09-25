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


def _profile_city(preferences: Dict[str, Any]) -> str:
    location = preferences.get("location")
    if isinstance(location, dict):
        return str(location.get("city") or "")
    if isinstance(location, str):
        return location
    return ""


def build_user_context(user_id: int, user_name: str = "", lat: str = "",
                       lng: str = "", city: str = "") -> UserContext:
    """装配上下文。任何一环取不到都不阻断对话：偏好按空处理、姓名退回占位。

    WebSocket 层只掌握 user_id，所以姓名与城市要自己能从库里补齐；显式传入的
    参数优先（便于前端覆盖）。
    """
    context = UserContext(user_id=user_id, user_name=user_name, lat=lat, lng=lng, city=city)
    try:
        from service.service_manager import service_manager
        from service.services.preference_service import PreferenceService

        preference_service = service_manager.get_service("preference_service", PreferenceService)
        context.preferences = preference_service.get_all_user_preferences(user_id) or {}
    except Exception as exc:
        logger.warning(f"加载用户 {user_id} 偏好失败，按空偏好继续: {exc}")

    if not context.city:
        context.city = _profile_city(context.preferences)

    if not context.user_name:
        try:
            from service.service_manager import service_manager
            from service.services.user_service import UserService

            user = service_manager.get_service("user_service", UserService).get_user(user_id)
            context.user_name = (getattr(user, "name", "") or "") if user else ""
        except Exception as exc:
            logger.warning(f"加载用户 {user_id} 姓名失败: {exc}")
            context.user_name = ""

    if not context.user_name:
        context.user_name = f"User {user_id}"
    return context
