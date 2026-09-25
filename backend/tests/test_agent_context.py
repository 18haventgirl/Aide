"""UserContext 与 build_user_context"""

from agent.context import UserContext, build_user_context


def test_guardrail_list_is_not_shared_between_instances():
    a = UserContext(user_id=1)
    b = UserContext(user_id=2)
    a.guardrail_checks.append({"name": "x"})
    assert b.guardrail_checks == []


def test_build_context_maps_basic_fields():
    ctx = build_user_context(5, user_name="lg", lat="31.23", lng="121.47", city="上海")
    assert ctx.user_id == 5
    assert (ctx.user_name, ctx.lat, ctx.lng, ctx.city) == ("lg", "31.23", "121.47", "上海")
    assert ctx.preferences == {}
    assert ctx.guardrail_checks == []


def test_preferences_failure_degrades_to_empty(monkeypatch):
    """偏好服务不可用不能阻断对话"""
    import service.service_manager as sm

    def boom(*args, **kwargs):
        raise RuntimeError("数据库不可用")

    monkeypatch.setattr(sm.service_manager, "get_service", boom)
    ctx = build_user_context(6)
    assert ctx.preferences == {}
