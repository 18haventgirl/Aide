"""语言模型构造（LangChain 侧）

原实现用 litellm，模型名需要 provider 前缀（如 openai/deepseek-chat）；LangChain 走
OpenAI SDK，只要模型本名。这里在读配置时做一次去前缀，让迁移前写好的 .env 不至于
直接报错。
"""

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# 显式定位 backend/.env：自动查找依赖调用方位置，从别的入口启动时会找不到
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"


def resolve_model_name(raw: Optional[str]) -> str:
    """去掉 litellm 的 provider 前缀，只保留模型本名"""
    cleaned = (raw or "").strip()
    if cleaned.startswith("openai/"):
        return cleaned.split("/", 1)[1]
    return cleaned


def build_chat_model(temperature: float = 0.6, top_p: float = 0.9) -> Optional[ChatOpenAI]:
    """按环境变量构造对话模型；没有 API key 时返回 None，由调用方转成可读错误"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("未配置 OPENAI_API_KEY，无法构造对话模型")
        return None
    return ChatOpenAI(
        model=resolve_model_name(os.getenv("OPENAI_CHAT_MODEL", DEFAULT_MODEL)),
        api_key=api_key,
        base_url=os.getenv("OPENAI_API_BASE_URL", DEFAULT_BASE_URL),
        temperature=temperature,
        top_p=top_p,
    )
