"""
WebSocket 核心模块 (WebSocket Core Module)

AI 个人日常助手项目的 WebSocket 核心功能模块
提供完整的 WebSocket 连接管理、消息处理、房间管理等功能

主要组件 (Main Components):
- models: 数据模型定义 (Data model definitions)
- manager: 连接管理器 (Connection manager)
- handler: 消息处理器 (Message handler)
- utils: 工具函数 (Utility functions)

使用示例 (Usage Example):
```python
from core.web_socket_core import (
    connection_manager,
    WebSocketMessageHandler,
    WebSocketMessage,
    MessageType,
    UserInfo
)

# 创建消息处理器 (Create message handler)
handler = WebSocketMessageHandler(connection_manager)

# 创建用户信息 (Create user info)
user = UserInfo(user_id="user123", username="张三")

# 创建消息 (Create message)
message = WebSocketMessage(
    type=MessageType.CHAT,
    content="你好！(Hello!)",
    sender_id="user123"
)
```
"""

# 运行时配置 (Runtime configuration)
from core.runtime_config import RuntimeConfig

# 导入数据模型 (Import data models)
from .models import (
    MessageType,
    ConnectionStatus,
    UserInfo,
    WebSocketMessage,
    ConnectionInfo,
    RoomInfo,
    BroadcastMessage,
    WebSocketError
)

# 导入连接管理器 (Import connection manager)
from .manager import (
    WebSocketConnectionManager,
    connection_manager  # 全局单例实例 (Global singleton instance)
)

# 导入消息处理器 (Import message handler)
from .handler import (
    WebSocketMessageHandler
)

# 导入工具函数 (Import utility functions)
from .utils import (
    generate_connection_id,
    validate_message,
    parse_websocket_message,
    extract_query_params,
    create_error_message,
    sanitize_user_input
)

# 模块版本信息 (Module version info)
__version__ = "1.0.0"
__author__ = "AI Personal Daily Assistant Team"

# 导出的公共接口 (Public API exports)
__all__ = [
    # 数据模型 (Data Models)
    "MessageType",
    "ConnectionStatus", 
    "UserInfo",
    "WebSocketMessage",
    "ConnectionInfo",
    "RoomInfo",
    "BroadcastMessage",
    "WebSocketError",
    
    # 核心组件 (Core Components)
    "WebSocketConnectionManager",
    "connection_manager",
    "WebSocketMessageHandler",
    
    # 工具函数 (Utility Functions)
    "generate_connection_id",
    "validate_message",
    "parse_websocket_message",
    "extract_query_params",
    "create_error_message",
    "sanitize_user_input",
    
    # 版本信息 (Version Info)
    "__version__",
    "__author__"
]

# 模块初始化日志 (Module initialization logging)
import logging
logger = logging.getLogger(__name__)
logger.info(f"WebSocket 核心模块已加载 (WebSocket Core Module loaded) - Version {__version__}")

# 常用配置常量 (Common configuration constants)
class WebSocketConfig:
    """WebSocket 配置常量 (WebSocket configuration constants)"""
    
    # 默认端口 (Default port) —— 与 API 服务同端口，由 API_PORT 环境变量决定
    DEFAULT_PORT = RuntimeConfig.API_PORT
    
    # 心跳间隔（秒）(Heartbeat interval in seconds)
    HEARTBEAT_INTERVAL = 30
    
    # 连接超时时间（秒）(Connection timeout in seconds)
    CONNECTION_TIMEOUT = 90
    
    # 最大消息长度 (Maximum message length)
    MAX_MESSAGE_LENGTH = 10000
    
    # 最大房间成员数 (Maximum room members)
    MAX_ROOM_MEMBERS = 100
    
    # 支持的消息类型 (Supported message types)
    SUPPORTED_MESSAGE_TYPES = [e.value for e in MessageType]
    
    # 系统用户ID (System user ID)
    SYSTEM_USER_ID = "system"
    
    # 默认房间ID (Default room ID)
    DEFAULT_ROOM_ID = "general"


# 添加配置到导出列表 (Add config to exports)
__all__.append("WebSocketConfig") 