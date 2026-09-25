"""
WebSocket 工具函数 (WebSocket Utility Functions)
消息解析、校验与输入清理等 WebSocket 相关实用函数
"""

import json
import logging
import re
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from urllib.parse import parse_qs, urlparse
import secrets

from .models import (
    WebSocketMessage,
    MessageType,
    WebSocketError
)

# 配置日志 (Configure logging)
logger = logging.getLogger(__name__)


def generate_connection_id() -> str:
    """
    生成唯一的连接ID (Generate unique connection ID)
    
    Returns:
        str: 连接ID (Connection ID)
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    random_str = secrets.token_hex(8)
    return f"conn_{timestamp}_{random_str}"


def validate_message(message_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    验证 WebSocket 消息格式 (Validate WebSocket message format)
    
    Args:
        message_data: 消息数据字典 (Message data dictionary)
        
    Returns:
        Tuple[bool, Optional[str]]: (是否有效, 错误信息) (Is valid, Error message)
    """
    try:
        # 检查必需字段 (Check required fields)
        required_fields = ["type", "content"]
        for field in required_fields:
            if field not in message_data:
                return False, f"缺少必需字段 (Missing required field): {field}"
        
        # 检查消息类型是否有效 (Check if message type is valid)
        if message_data["type"] not in [e.value for e in MessageType]:
            return False, f"无效的消息类型 (Invalid message type): {message_data['type']}"
        
        # 检查内容字段 (Check content field)
        if "content" not in message_data or message_data["content"] is None:
            return False, "消息内容不能为空 (Message content cannot be empty)"
        
        # 检查可选字段的格式 (Check optional fields format)
        if "timestamp" in message_data:
            try:
                datetime.fromisoformat(message_data["timestamp"].replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                return False, "时间戳格式无效 (Invalid timestamp format)"
        
        return True, None
        
    except Exception as e:
        return False, f"消息验证错误 (Message validation error): {str(e)}"


def parse_websocket_message(raw_message: str) -> Tuple[Optional[WebSocketMessage], Optional[str]]:
    """
    解析 WebSocket 原始消息 (Parse WebSocket raw message)
    
    Args:
        raw_message: 原始消息字符串 (Raw message string)
        
    Returns:
        Tuple[Optional[WebSocketMessage], Optional[str]]: (解析后的消息, 错误信息) (Parsed message, Error message)
    """
    try:
        # 解析JSON (Parse JSON)
        message_data = json.loads(raw_message)
        
        # 验证消息格式 (Validate message format)
        is_valid, error_msg = validate_message(message_data)
        if not is_valid:
            return None, error_msg
        
        # 创建WebSocketMessage对象 (Create WebSocketMessage object)
        message = WebSocketMessage(**message_data)
        return message, None
        
    except json.JSONDecodeError as e:
        return None, f"JSON解析错误 (JSON parsing error): {str(e)}"
    except Exception as e:
        return None, f"消息解析错误 (Message parsing error): {str(e)}"


def create_error_message(error_code: str, error_message: str, connection_id: Optional[str] = None) -> WebSocketMessage:
    """
    创建错误消息 (Create error message)
    
    Args:
        error_code: 错误代码 (Error code)
        error_message: 错误消息 (Error message)
        connection_id: 连接ID (Connection ID)
        
    Returns:
        WebSocketMessage: 错误消息对象 (Error message object)
    """
    error_content = WebSocketError(
        error_code=error_code,
        error_message=error_message,
        error_type="websocket_error",
        connection_id=connection_id
    )
    
    return WebSocketMessage(
        type=MessageType.ERROR,
        content=error_content.model_dump(),
        sender_id="system",
        receiver_id=None,
        room_id=None,
        timestamp=datetime.utcnow()
    )


def extract_query_params(url: str) -> Dict[str, str]:
    """
    从 WebSocket URL 中提取查询参数 (Extract query parameters from WebSocket URL)
    
    Args:
        url: WebSocket 连接URL (WebSocket connection URL)
        
    Returns:
        Dict[str, str]: 查询参数字典 (Query parameters dictionary)
    """
    try:
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        
        # 将列表值转换为单个字符串 (Convert list values to single strings)
        result = {}
        for key, value_list in query_params.items():
            result[key] = value_list[0] if value_list else ""
        
        return result
    except Exception as e:
        logger.error(f"URL参数解析错误 (URL parameter parsing error): {e}")
        return {}


def sanitize_user_input(user_input: str, max_length: int = 1000) -> str:
    """
    清理用户输入 (Sanitize user input)
    
    Args:
        user_input: 用户输入字符串 (User input string)
        max_length: 最大长度限制 (Maximum length limit)
        
    Returns:
        str: 清理后的输入 (Sanitized input)
    """
    if not isinstance(user_input, str):
        return ""
    
    # 移除潜在危险字符 (Remove potentially dangerous characters)
    sanitized = re.sub(r'[<>"\']', '', user_input)
    
    # 限制长度 (Limit length)
    sanitized = sanitized[:max_length]
    
    # 移除首尾空白字符 (Strip whitespace)
    sanitized = sanitized.strip()
    
    return sanitized
