"""WebSocket 消息工具函数的冒烟测试（不需要数据库与网络）"""

from core.web_socket_core import MessageType
from core.web_socket_core.utils import (
    extract_query_params,
    parse_websocket_message,
    sanitize_user_input,
    validate_message,
)


def test_validate_message_accepts_minimal_payload():
    is_valid, error = validate_message({"type": MessageType.CHAT.value, "content": "你好"})

    assert is_valid, error
    assert error is None


def test_validate_message_rejects_missing_content():
    is_valid, error = validate_message({"type": MessageType.CHAT.value})

    assert not is_valid
    assert "content" in error


def test_validate_message_rejects_unknown_type():
    is_valid, error = validate_message({"type": "not_a_type", "content": "x"})

    assert not is_valid
    assert "not_a_type" in error


def test_parse_websocket_message_roundtrip():
    raw = '{"type": "chat", "content": {"text": "明天北京天气"}}'

    message, error = parse_websocket_message(raw)

    assert error is None
    assert message is not None
    assert message.type is MessageType.CHAT
    assert message.content["text"] == "明天北京天气"


def test_parse_websocket_message_rejects_bad_json():
    message, error = parse_websocket_message("{not json")

    assert message is None
    assert "JSON" in error


def test_parse_websocket_message_rejects_bad_timestamp():
    raw = '{"type": "chat", "content": "x", "timestamp": "昨天下午"}'

    message, error = parse_websocket_message(raw)

    assert message is None
    assert "时间戳" in error


def test_sanitize_user_input_strips_markup_and_truncates():
    assert sanitize_user_input('<script>alert("x")</script>') == "scriptalert(x)/script"
    assert len(sanitize_user_input("a" * 50, max_length=10)) == 10
    assert sanitize_user_input(None) == ""


def test_extract_query_params_from_ws_handshake_url():
    params = extract_query_params(
        "ws://127.0.0.1:8100/ws?user_id=7&conversation_id=abc&token=jwt-here"
    )

    assert params == {
        "user_id": "7",
        "conversation_id": "abc",
        "token": "jwt-here",
    }
