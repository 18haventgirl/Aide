"""UserContext 与 build_user_context"""

from types import SimpleNamespace

from agent.context import UserContext, build_user_context


class _FakeServices:
    """按 service_class 分派替身，模拟 service_manager.get_service"""

    def __init__(self, user=None, preferences=None, boom=False):
        self.user = user
        self.preferences = preferences if preferences is not None else {}
        self.boom = boom

    def __call__(self, name, cls=None, **kwargs):
        if self.boom:
            raise RuntimeError("数据库不可用")
        if name == "user_service":
            return SimpleNamespace(get_user=lambda uid: self.user)
        return SimpleNamespace(get_all_user_preferences=lambda uid: self.preferences)


def _patch_manager(monkeypatch, fake):
    import service.service_manager as sm

    monkeypatch.setattr(sm.service_manager, "get_service", fake)


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


def test_user_name_and_city_fall_back_to_profile_when_not_given(monkeypatch):
    """WebSocket 层只给得出 user_id，姓名与城市要自己能从库里取到"""
    _patch_manager(monkeypatch, _FakeServices(
        user=SimpleNamespace(name="老王"),
        preferences={"location": {"city": "杭州"}},
    ))
    ctx = build_user_context(7)
    assert ctx.user_name == "老王"
    assert ctx.city == "杭州"
    assert ctx.preferences == {"location": {"city": "杭州"}}


def test_explicit_arguments_win_over_profile(monkeypatch):
    _patch_manager(monkeypatch, _FakeServices(
        user=SimpleNamespace(name="老王"),
        preferences={"location": {"city": "杭州"}},
    ))
    ctx = build_user_context(7, user_name="前端传的名", city="上海")
    assert (ctx.user_name, ctx.city) == ("前端传的名", "上海")


def test_missing_profile_degrades_to_placeholder_name(monkeypatch):
    _patch_manager(monkeypatch, _FakeServices(user=None, preferences={}))
    ctx = build_user_context(8)
    assert ctx.user_name == "User 8"


def test_preferences_failure_degrades_to_empty(monkeypatch):
    """偏好服务不可用不能阻断对话"""
    _patch_manager(monkeypatch, _FakeServices(boom=True))
    ctx = build_user_context(6)
    assert ctx.preferences == {}
    assert ctx.user_name == "User 6"
