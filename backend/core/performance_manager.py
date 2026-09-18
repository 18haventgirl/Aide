"""
全局性能管理器

统一管理agent单例、会话管理器缓存、用户上下文缓存等，提高多用户并发性能
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Any, List
from threading import RLock
from datetime import datetime, timedelta

from agent.personal_assistant_manager import PersonalAssistantManager, PersonalAssistantContext
from agent.agent_session import AgentSessionManager
from service.service_manager import service_manager


class PerformanceManager:
    """
    全局性能管理器
    
    负责管理agent单例、会话管理器缓存、用户上下文缓存等，
    提高多用户并发场景下的性能
    """
    
    def __init__(self):
        self._lock = RLock()
        self._logger = logging.getLogger(__name__)
        
        # Agent管理器单例
        self._assistant_manager: Optional[PersonalAssistantManager] = None
        self._assistant_manager_initialized = False
        
        # 会话管理器缓存 - 按用户ID缓存
        self._session_managers: Dict[int, AgentSessionManager] = {}
        
        # 用户上下文缓存
        self._user_contexts: Dict[int, PersonalAssistantContext] = {}
        self._context_cache_expiry: Dict[int, datetime] = {}
        self._context_cache_duration = timedelta(minutes=10)  # 10分钟缓存
        
        # 性能统计
        self._stats = {
            "agent_manager_hits": 0,
            "session_manager_hits": 0,
            "session_manager_creates": 0,
            "context_cache_hits": 0,
            "context_cache_misses": 0,
            "total_requests": 0,
            "start_time": time.time()
        }
        
        # 初始化状态
        self._initialized = False
    
    async def initialize(self) -> bool:
        """初始化性能管理器"""
        if self._initialized:
            return True
        
        with self._lock:
            try:
                self._logger.info("🚀 开始初始化性能管理器...")
                
                # 确保service_manager已初始化
                if not service_manager.initialize():
                    self._logger.error("❌ Service manager初始化失败")
                    return False
                
                # 初始化全局assistant manager
                await self._initialize_assistant_manager()
                
                self._initialized = True
                self._logger.info("✅ 性能管理器初始化完成")
                return True
                
            except Exception as e:
                self._logger.error(f"❌ 性能管理器初始化失败: {e}")
                return False
    
    async def _initialize_assistant_manager(self):
        """初始化全局assistant manager单例"""
        if self._assistant_manager_initialized:
            return
        
        try:
            self._logger.info("🤖 初始化全局Assistant Manager...")
            
            # 从service_manager获取共享的数据库客户端
            db_client = service_manager.get_db_client()
            if not db_client:
                raise RuntimeError("无法获取数据库客户端")
            
            # 创建assistant manager
            self._assistant_manager = PersonalAssistantManager(
                db_client=db_client,
                mcp_server_url="http://localhost:8002/mcp"
            )
            
            # 初始化assistant manager
            success = await self._assistant_manager.initialize()
            if not success:
                raise RuntimeError("Assistant manager初始化失败")
            
            self._assistant_manager_initialized = True
            self._logger.info("✅ 全局Assistant Manager初始化完成")
            
        except Exception as e:
            self._logger.error(f"❌ 初始化Assistant Manager失败: {e}")
            raise
    
    def get_assistant_manager(self) -> PersonalAssistantManager:
        """
        获取全局assistant manager单例
        
        Returns:
            PersonalAssistantManager实例
            
        Raises:
            RuntimeError: 如果未初始化
        """
        if not self._initialized or not self._assistant_manager_initialized or self._assistant_manager is None:
            raise RuntimeError("性能管理器尚未初始化")
        
        self._stats["agent_manager_hits"] += 1
        return self._assistant_manager
    
    def get_session_manager(self, user_id: int) -> AgentSessionManager:
        """
        获取用户的会话管理器（缓存复用）
        
        Args:
            user_id: 用户ID
            
        Returns:
            AgentSessionManager实例
        """
        if not self._initialized:
            raise RuntimeError("性能管理器尚未初始化")
        
        # 检查缓存
        if user_id in self._session_managers:
            self._stats["session_manager_hits"] += 1
            return self._session_managers[user_id]
        
        # 创建新的会话管理器
        with self._lock:
            # 双重检查锁定
            if user_id in self._session_managers:
                self._stats["session_manager_hits"] += 1
                return self._session_managers[user_id]
            
            # 使用service_manager提供的共享数据库客户端
            db_client = service_manager.get_db_client()
            if not db_client:
                raise RuntimeError("无法获取数据库客户端")
            
            session_manager = AgentSessionManager(
                db_client=db_client,
                default_user_id=user_id,
                max_messages=100
            )
            
            self._session_managers[user_id] = session_manager
            self._stats["session_manager_creates"] += 1
            
            self._logger.info(f"✅ 为用户 {user_id} 创建新的会话管理器")
            return session_manager

    async def evict_conversation(self, user_id: int, conversation_id: str) -> bool:
        """Clear cached message history after a conversation is deleted."""
        manager = self._session_managers.get(user_id)
        return await manager.remove_conversation(conversation_id) if manager else True
    
    def get_user_context(self, user_id: int, force_refresh: bool = False) -> PersonalAssistantContext:
        """
        获取用户上下文（带缓存）
        
        Args:
            user_id: 用户ID
            force_refresh: 强制刷新缓存
            
        Returns:
            PersonalAssistantContext实例
        """
        if not self._initialized:
            raise RuntimeError("性能管理器尚未初始化")
        
        # 检查缓存
        if not force_refresh and user_id in self._user_contexts:
            if datetime.now() < self._context_cache_expiry.get(user_id, datetime.min):
                self._stats["context_cache_hits"] += 1
                self._logger.debug(f"🎯 用户 {user_id} 上下文缓存命中")
                return self._user_contexts[user_id]
        
        # 缓存未命中或过期
        self._stats["context_cache_misses"] += 1
        
        with self._lock:
            # 双重检查锁定
            if not force_refresh and user_id in self._user_contexts:
                if datetime.now() < self._context_cache_expiry.get(user_id, datetime.min):
                    self._stats["context_cache_hits"] += 1
                    return self._user_contexts[user_id]
            
            # 创建新的用户上下文
            try:
                self._logger.info(f"🔄 刷新用户 {user_id} 的上下文缓存")
                
                if self._assistant_manager is None:
                    raise RuntimeError("Assistant manager未初始化")
                
                context = self._assistant_manager.create_user_context(user_id)
                
                # 缓存上下文
                self._user_contexts[user_id] = context
                self._context_cache_expiry[user_id] = datetime.now() + self._context_cache_duration
                
                self._logger.debug(f"✅ 用户 {user_id} 上下文已缓存")
                return context
                
            except Exception as e:
                self._logger.error(f"❌ 创建用户 {user_id} 上下文失败: {e}")
                raise
    
    def invalidate_user_context(self, user_id: int):
        """
        使指定用户的上下文缓存失效
        
        Args:
            user_id: 用户ID
        """
        with self._lock:
            if user_id in self._user_contexts:
                del self._user_contexts[user_id]
            if user_id in self._context_cache_expiry:
                del self._context_cache_expiry[user_id]
            self._logger.info(f"🗑️ 已清除用户 {user_id} 的上下文缓存")
    
    def get_agent_by_name(self, agent_name: str):
        """
        获取指定名称的agent（使用全局assistant manager）
        
        Args:
            agent_name: agent名称
            
        Returns:
            Agent实例
        """
        assistant_manager = self.get_assistant_manager()
        
        # 映射agent名称到管理器方法
        agent_mapping = {
            "Triage Agent": assistant_manager.get_triage_agent,
            "Weather Agent": assistant_manager.get_weather_agent,
            "News Agent": assistant_manager.get_news_agent,
            "Recipe Agent": assistant_manager.get_recipe_agent,
            "Personal Assistant Agent": assistant_manager.get_personal_agent,
            "Medical Knowledge Agent": assistant_manager.get_medical_agent,
            "Conversation Title Agent": assistant_manager.get_conversation_title_agent,
        }
        
        if agent_name in agent_mapping:
            return agent_mapping[agent_name]()
        else:
            # 默认返回任务调度中心
            self._logger.warning(f"Agent '{agent_name}' 未找到，返回Triage Agent")
            return assistant_manager.get_triage_agent()
    
    def cleanup_expired_caches(self):
        """清理过期的缓存"""
        now = datetime.now()
        expired_contexts = []
        
        with self._lock:
            # 找出过期的上下文缓存
            for user_id, expiry_time in self._context_cache_expiry.items():
                if now >= expiry_time:
                    expired_contexts.append(user_id)
            
            # 删除过期的缓存
            for user_id in expired_contexts:
                if user_id in self._user_contexts:
                    del self._user_contexts[user_id]
                if user_id in self._context_cache_expiry:
                    del self._context_cache_expiry[user_id]
            
            if expired_contexts:
                self._logger.info(f"🧹 清理了 {len(expired_contexts)} 个过期的用户上下文缓存")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取性能统计信息"""
        self._stats["total_requests"] += 1
        self._stats["uptime_seconds"] = int(time.time() - self._stats["start_time"])
        self._stats["cached_session_managers"] = len(self._session_managers)
        self._stats["cached_user_contexts"] = len(self._user_contexts)
        
        return self._stats.copy()
    
    def close(self):
        """关闭性能管理器，清理资源"""
        with self._lock:
            try:
                # 关闭所有会话管理器
                for session_manager in self._session_managers.values():
                    try:
                        session_manager.close()
                    except Exception as e:
                        self._logger.error(f"关闭会话管理器失败: {e}")
                
                # 清理缓存
                self._session_managers.clear()
                self._user_contexts.clear()
                self._context_cache_expiry.clear()
                
                self._initialized = False
                self._assistant_manager_initialized = False
                self._assistant_manager = None
                
                self._logger.info("🛑 性能管理器已关闭")
                
            except Exception as e:
                self._logger.error(f"关闭性能管理器失败: {e}")


# 全局性能管理器实例
performance_manager = PerformanceManager()
