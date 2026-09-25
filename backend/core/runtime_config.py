"""集中式运行时配置

端口、监听地址与跨域白名单全部由环境变量驱动，避免在代码里散落硬编码。
"""

import os
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"环境变量 {name} 必须是整数，当前值: {raw!r}")


class RuntimeConfig:
    """应用级运行时配置"""

    API_HOST = os.getenv("API_HOST", "0.0.0.0")
    API_PORT = _env_int("API_PORT", 8100)

    MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
    MCP_PORT = _env_int("MCP_PORT", 8102)
    MCP_PATH = os.getenv("MCP_PATH", "/mcp")

    # 智能体连接 MCP 服务使用的完整地址，可用 MCP_SERVER_URL 覆盖（例如指向远程 MCP）
    MCP_SERVER_URL = os.getenv("MCP_SERVER_URL") or f"http://{MCP_HOST}:{MCP_PORT}{MCP_PATH}"

    # 前端开发服务器端口，仅用于生成默认 CORS 白名单
    UI_PORT = _env_int("UI_PORT", 5199)

    @classmethod
    def mcp_bind(cls) -> tuple:
        return cls.MCP_HOST, cls.MCP_PORT, cls.MCP_PATH

    @classmethod
    def api_origin(cls, scheme: str = "http") -> str:
        host = "127.0.0.1" if cls.API_HOST in ("0.0.0.0", "::") else cls.API_HOST
        return f"{scheme}://{host}:{cls.API_PORT}"


def cors_origins() -> List[str]:
    """CORS 允许的来源列表

    通过 CORS_ORIGINS 覆盖（逗号分隔）。默认只放行本机前端开发服务器，
    不再使用通配符 —— 应用启用了 allow_credentials，通配符等于放开跨站携带凭据。
    """
    configured = os.getenv("CORS_ORIGINS")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]

    ui_port = RuntimeConfig.UI_PORT
    defaults = set()
    for scheme in ("http", "https"):
        for host in ("localhost", "127.0.0.1"):
            for port in (ui_port, 5173):
                defaults.add(f"{scheme}://{host}:{port}")
    return sorted(defaults)
