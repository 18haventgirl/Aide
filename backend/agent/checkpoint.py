"""对话状态检查点（SQLite）

checkpoint 是对话状态的唯一真相：多轮记忆、恢复、时间旅行都来自它。MySQL 的
conversations / chat_messages 只作展示与检索副本，不再回灌给模型当记忆。
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger(__name__)

DEFAULT_PATH = "data/lg-aide-checkpoints.sqlite"


def checkpoint_path() -> str:
    """CHECKPOINT_DB 覆盖；默认相对 backend 工作目录，避免把绝对路径写死进仓库"""
    return os.getenv("CHECKPOINT_DB", DEFAULT_PATH)


@asynccontextmanager
async def build_checkpointer() -> AsyncIterator[AsyncSqliteSaver]:
    """调用方要长期持有这个上下文，不要建完图就退出——退出即关闭连接，下一轮必炸"""
    path = checkpoint_path()
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        logger.info(f"checkpoint 就绪: {path}")
        yield saver
