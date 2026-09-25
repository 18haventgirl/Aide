"""
全局性能管理器

编排层切到 LangGraph 后，这里只剩一件仍有意义的事：按用户缓存会话管理器
（MySQL 展示副本的读写入口）。图与工具由 agent.runtime.aide_runtime 自行懒构建，
用户上下文每轮现取，都不再需要缓存层。
"""

import logging
import time
from threading import RLock
from typing import Any, Dict

from agent.agent_session import AgentSessionManager
from service.service_manager import service_manager


class PerformanceManager:
    """按用户缓存 AgentSessionManager，避免每条消息重建数据库对象"""

    def __init__(self):
        self._lock = RLock()
        self._logger = logging.getLogger(__name__)

        self._session_managers: Dict[int, AgentSessionManager] = {}
        self._initialized = False

        self._stats = {
            "session_manager_hits": 0,
            "session_manager_creates": 0,
            "total_requests": 0,
            "start_time": time.time(),
        }

    async def initialize(self) -> bool:
        """初始化性能管理器（只需保证 service_manager 就绪）"""
        if self._initialized:
            return True

        with self._lock:
            if self._initialized:
                return True
            if not service_manager.initialize():
                self._logger.error("Service manager 初始化失败")
                return False
            self._initialized = True
            self._logger.info("性能管理器初始化完成")
            return True

    def get_session_manager(self, user_id: int) -> AgentSessionManager:
        """获取用户的会话管理器（缓存复用）"""
        if not self._initialized:
            raise RuntimeError("性能管理器尚未初始化")

        cached = self._session_managers.get(user_id)
        if cached is not None:
            self._stats["session_manager_hits"] += 1
            return cached

        with self._lock:
            cached = self._session_managers.get(user_id)
            if cached is not None:
                self._stats["session_manager_hits"] += 1
                return cached

            db_client = service_manager.get_db_client()
            if not db_client:
                raise RuntimeError("无法获取数据库客户端")

            session_manager = AgentSessionManager(
                db_client=db_client, default_user_id=user_id, max_messages=100
            )
            self._session_managers[user_id] = session_manager
            self._stats["session_manager_creates"] += 1
            self._logger.info(f"为用户 {user_id} 创建新的会话管理器")
            return session_manager

    def get_stats(self) -> Dict[str, Any]:
        """获取性能统计信息"""
        self._stats["total_requests"] += 1
        self._stats["uptime_seconds"] = int(time.time() - self._stats["start_time"])
        self._stats["cached_session_managers"] = len(self._session_managers)
        return self._stats.copy()

    def close(self):
        """关闭性能管理器，释放所有会话管理器"""
        with self._lock:
            for session_manager in self._session_managers.values():
                try:
                    session_manager.close()
                except Exception as exc:
                    self._logger.error(f"关闭会话管理器失败: {exc}")

            self._session_managers.clear()
            self._initialized = False
            self._logger.info("性能管理器已关闭")


# 全局性能管理器实例
performance_manager = PerformanceManager()
