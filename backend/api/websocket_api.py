"""
WebSocket API模块

包含WebSocket连接、广播消息、连接管理等相关的API端点
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import uuid4
from asyncio import Queue, create_task

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query

# 导入认证核心模块
from core.auth_core import CurrentUser

# 导入服务管理器
from service.service_manager import service_manager

# 导入 agent 相关模块（编排层已切到 LangGraph）
from agent.agent_session import AgentSessionManager
from agent.context import build_user_context
from agent.runtime import aide_runtime
from api.ws_stream import (
    ChatResponse,
    GuardrailCheck,
    WsStreamTranslator,
)

# 导入WebSocket核心模块
from core.web_socket_core import (
    connection_manager,
    WebSocketMessage,
    MessageType,
    UserInfo,
    parse_websocket_message,
    validate_message,
    create_error_message,
    generate_connection_id
)

# 导入性能管理器
from core.performance_manager import performance_manager

# 配置日志
logger = logging.getLogger(__name__)

# 创建WebSocket API路由器
websocket_router = APIRouter(tags=["WebSocket"])

# 响应模型（ChatResponse 等）定义在 api/ws_stream.py，这里直接复用

# =========================
# 全局变量（从main中移过来的）
# =========================
# 用户会话映射（保留全局状态跟踪）
user_conversations: Dict[str, str] = {}

# =========================
# 辅助函数
# =========================

def _context_snapshot(context) -> Dict[str, Any]:
    """UserContext → ChatResponse.context 的只读快照（前端面板按这个渲染）"""
    return {
        "user_id": context.user_id,
        "user_name": context.user_name,
        "lat": context.lat,
        "lng": context.lng,
        "city": context.city,
        "user_preferences": context.preferences,
    }


def _build_agents_list() -> List[Dict[str, Any]]:
    """图上的代理清单：单代理 + 它挂的工具名

    字段与旧引擎保持一致（name/description/handoffs/tools/input_guardrails），
    handoffs 恒为空 —— 6 代理 handoff 结构已被单 agent + 工具图取代。
    """
    from agent.runtime import aide_runtime

    return [{
        "name": "Aide",
        "description": "LangGraph 单代理 + 工具图（自研 RAG 笔记 + MCP 外部数据）",
        "handoffs": [],
        "tools": [tool["name"] for tool in aide_runtime.tools_manifest()],
        "input_guardrails": ["Safety Guardrail", "Relevance Guardrail"],
    }]


def _guardrail_checks(checks: List[Dict[str, Any]]) -> List[GuardrailCheck]:
    now = datetime.now().timestamp()
    return [
        GuardrailCheck(
            id=f"guardrail-{index}",
            name=str(check.get("name", "Guardrail")),
            input=str(check.get("input", "")),
            reasoning=str(check.get("reasoning", "")),
            passed=bool(check.get("passed", True)),
            timestamp=now,
        )
        for index, check in enumerate(checks or [])
    ]


def _fallback_response(conversation_id: str, user_id: str, error: str,
                       guardrails: Optional[List[Dict[str, Any]]] = None) -> ChatResponse:
    """引擎之外出错时（拿不到会话等）也要给前端一条能收尾的完整响应"""
    return ChatResponse(
        conversation_id=conversation_id,
        current_agent="System",
        messages=[],
        events=[],
        context={},
        agents=_build_agents_list(),
        raw_response="",
        guardrails=_guardrail_checks(guardrails or []),
        is_finished=True,
        is_error=True,
        error_message=error,
    )


def _completion_frame(response: ChatResponse, note: str, room_id: str) -> WebSocketMessage:
    return WebSocketMessage(
        type=MessageType.AI_RESPONSE,
        content={"type": "completion", "final_response": response.model_dump(), "message": note},
        sender_id="system",
        receiver_id=None,
        room_id=room_id,
    )

# =========================
# 服务初始化函数
# =========================

async def ensure_services_initialized():
    """确保服务已初始化（已优化使用性能管理器）"""
    if not performance_manager._initialized:
        success = await performance_manager.initialize()
        if not success:
            raise RuntimeError("性能管理器初始化失败")

def get_session_manager_for_user(user_id: int) -> AgentSessionManager:
    """为特定用户获取会话管理器（已优化使用缓存）"""
    return performance_manager.get_session_manager(user_id)

# =========================
# 流式处理函数
# =========================

def _completion_note(answer) -> str:
    if answer.blocked:
        return "输入被护栏拦截"
    if answer.error:
        return "处理过程中发生错误"
    return "对话完成"


async def _maybe_update_title(conversation_id: str, user_text: str, answer,
                              agent_session, session_manager) -> None:
    """新会话的头几轮起个标题；失败就保留原标题，绝不影响已完成的对话"""
    from agent.model import generate_conversation_title

    if answer.error or not answer.text:
        return
    try:
        items = agent_session.get_state().get("input_items", [])
    except Exception as exc:
        logger.debug(f"读取会话消息数失败，跳过标题生成: {exc}")
        return
    if not 1 < len(items) < 5:
        return
    try:
        title = await generate_conversation_title(user_text, answer.text)
        if title:
            await session_manager.update_conversation_title(conversation_id, title)
    except Exception as exc:
        logger.warning(f"会话标题更新失败: {exc}")


async def _process_stream_with_concurrent_handling(
    user_id: str, conversation_id: str, message: str, connection_id: str,
    context, agent_session, session_manager,
) -> None:
    """并发流式处理：LangGraph 事件边到边下发，收尾统一一条 completion

    发送队列与落库队列分开：慢客户端只拖慢自己那条连接的投递，不阻塞图执行；
    助手消息在 completion 之前入队，前端刷新历史时不会读到空。
    """
    from agent.runtime import AideAnswer, aide_runtime

    room_id = f"user_{user_id}_room"

    try:
        await aide_runtime.ensure_ready()
    except Exception as exc:
        logger.error(f"用户 {user_id} 引擎启动失败: {exc}")
        await _send_direct(connection_id, room_id, _completion_frame(
            _fallback_response(conversation_id, user_id, str(exc), context.guardrail_checks),
            "AI处理启动失败", room_id))
        return

    # 工具清单要等图建好才有内容，所以 translator 放在 ready 之后
    translator = WsStreamTranslator(
        user_id=str(user_id),
        connection_id=connection_id,
        conversation_id=conversation_id,
        context=_context_snapshot(context),
        tools_manifest=aide_runtime.tools_manifest(),
    )

    response_queue = asyncio.Queue()
    db_save_queue = asyncio.Queue()
    sender_task = create_task(_concurrent_response_sender(response_queue, connection_id))
    saver_task = create_task(_concurrent_db_saver(db_save_queue, agent_session))

    try:
        await response_queue.put(translator.tools_list_message())

        answer = None
        async for event in aide_runtime.astream(int(user_id), conversation_id, message,
                                                context=context):
            if event["kind"] == "final":
                answer = event["answer"]
                continue
            frame = await translator.feed(event)
            if frame is not None:
                await response_queue.put(frame)

        if answer is None:
            answer = AideAnswer(error="图未产出最终结果")
        if answer.text:
            await db_save_queue.put(("final_message", answer.text))

        await response_queue.put(_completion_frame(
            translator.build_chat_response(answer), _completion_note(answer), room_id))
        await response_queue.put(None)
        await db_save_queue.put(None)
        await asyncio.gather(sender_task, saver_task, return_exceptions=True)

        await _maybe_update_title(conversation_id, message, answer,
                                  agent_session, session_manager)
        logger.info(f"用户 {user_id} 流式处理完成")

    except Exception as exc:
        logger.exception(f"用户 {user_id} 流式处理出错")
        for task in (sender_task, saver_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(sender_task, saver_task, return_exceptions=True)
        await _send_direct(connection_id, room_id, _completion_frame(
            _fallback_response(conversation_id, user_id, str(exc), context.guardrail_checks),
            "处理过程中发生错误", room_id))


async def _send_direct(connection_id: str, room_id: str, message: WebSocketMessage) -> None:
    """直发一帧，用于队列可能已经出问题的兜底路径"""
    try:
        await connection_manager.send_to_connection(connection_id, message)
    except Exception as exc:
        logger.error(f"向连接 {connection_id} 发送消息失败: {exc}")
async def _concurrent_response_sender(response_queue: asyncio.Queue, connection_id: str):
    """并发响应发送器"""
    try:
        while True:
            message = await response_queue.get()
            if message is None:  # 停止信号
                break
            
            await connection_manager.send_to_connection(connection_id, message)
            await asyncio.sleep(0)  # 让出控制权
            
    except Exception as e:
        logger.error(f"响应发送器错误: {e}")


async def _concurrent_db_saver(db_save_queue: asyncio.Queue, agent_session):
    """并发数据库保存器"""
    try:
        while True:
            item = await db_save_queue.get()
            if item is None:  # 停止信号
                break
            
            save_type, data = item
            if save_type == "final_message":
                await agent_session.save_message(data, "assistant")
            
            await asyncio.sleep(0)  # 让出控制权
            
    except Exception as e:
        logger.error(f"数据库保存器错误: {e}")


async def handle_stream_chat(user_id: str, message: str, connection_id: str, authenticated_user: Optional[Dict[str, Any]] = None, conversation_id: Optional[str] = None) -> None:
    """处理流式聊天消息"""
    try:
        # 确保服务已初始化
        await ensure_services_initialized()

        room_id = f"user_{user_id}_room"
        fallback_conversation_id = conversation_id or f"user_{user_id}_conversation"
        try:
            session_manager = get_session_manager_for_user(int(user_id))
        except Exception as exc:
            logger.error(f"获取会话管理器失败: {exc}")
            await _send_direct(connection_id, room_id, _completion_frame(
                _fallback_response(fallback_conversation_id, user_id, str(exc)),
                "获取会话管理器失败", room_id))
            return
        
        # 装配本轮上下文（姓名/坐标/偏好）；同一个对象复用给图和响应，不查两遍
        ctx = build_user_context(int(user_id))

        # 会话：没传 ID 就开一个新的，用户消息先落库
        conversation_id = conversation_id or uuid4().hex
        user_conversations[user_id] = conversation_id
        room_id = f"user_{user_id}_room"
        try:
            agent_session = await session_manager.get_session(conversation_id)
        except Exception as exc:
            logger.error(f"创建或获取会话时发生错误: {exc}")
            agent_session = None

        if agent_session is None:
            await _send_direct(connection_id, room_id, _completion_frame(
                _fallback_response(conversation_id, user_id, f"无法创建会话 {conversation_id}"),
                "无法创建会话", room_id))
            return

        await agent_session.save_message(message, "user")

        await _process_stream_with_concurrent_handling(
            user_id, conversation_id, message, connection_id,
            ctx, agent_session, session_manager)
        logger.info(f"用户 {user_id} 流式处理任务完成")
        
    except Exception as e:
        logger.error(f"流式聊天处理错误: {e}")
        
        # 尝试把错误也记进会话（会话还在的话），再补一条能收尾的 completion
        conversation_id = user_conversations.get(user_id) or f"user_{user_id}_conversation"
        room_id = f"user_{user_id}_room"
        try:
            error_session_manager = get_session_manager_for_user(int(user_id))
            agent_session = await error_session_manager.get_session(conversation_id)
            if agent_session is not None:
                await agent_session.save_message(f"处理错误: {str(e)}", "assistant")
        except Exception as save_error:
            logger.error(f"保存错误信息到会话失败: {save_error}")

        await _send_direct(connection_id, room_id, _completion_frame(
            _fallback_response(conversation_id, user_id, str(e)), "流式处理失败", room_id))

# =========================
# WebSocket消息处理器（更新版本）
# =========================
from core.web_socket_core import WebSocketMessageHandler

class CustomMessageHandler(WebSocketMessageHandler):
    """自定义消息处理器，支持流式输出和并行处理"""
    
    def __init__(self, connection_manager):
        super().__init__(connection_manager)
        # 用于异步消息处理的队列和任务池
        self._message_queue: Queue = Queue()
        self._processing_tasks: Dict[str, asyncio.Task] = {}
        self._stats = {
            "messages_processed": 0,
            "messages_queued": 0,
            "active_tasks": 0,
            "errors": 0
        }
    
    async def handle_chat(self, connection_id: str, message: WebSocketMessage, authenticated_user: Optional[Dict[str, Any]] = None):
        """处理聊天消息 - 支持流式输出和并行处理"""
        logger.debug(f"🔄 接收流式聊天消息: {connection_id}")
        
        # 获取发送者信息
        conn_info = await self.connection_manager.get_connection_info(connection_id)
        if not conn_info or not conn_info.user_info:
            # 发送错误消息
            error_message = WebSocketMessage(
                type=MessageType.ERROR,
                content={"error": "未认证用户无法发送聊天消息"},
                sender_id="system",
                receiver_id=None,
                room_id=None,
                timestamp=datetime.utcnow()
            )
            await self.connection_manager.send_to_connection(connection_id, error_message)
            return

        # 获取用户ID和消息内容
        user_id = conn_info.user_info.user_id
        message_content = message.content
        
        if isinstance(message_content, dict):
            message_content = message_content.get("message", "")
        
        # 获取会话ID（从消息metadata中获取）
        conversation_id = message.metadata.get("conversation_id") if message.metadata else None
        
        # 异步处理消息（不阻塞其他用户）
        task_id = f"{connection_id}_{datetime.utcnow().timestamp()}"
        task = create_task(self._process_chat_async(
            user_id, str(message_content), connection_id, authenticated_user, conversation_id, task_id
        ))
        
        # 跟踪任务
        self._processing_tasks[task_id] = task
        self._stats["messages_queued"] += 1
        self._stats["active_tasks"] = len(self._processing_tasks)
        
        logger.info(f"🚀 用户 {user_id} 消息已加入异步处理队列 (任务ID: {task_id[:8]}...)")
        
        # 清理完成的任务
        task.add_done_callback(lambda t: self._cleanup_task(task_id))
    
    async def _process_chat_async(self, user_id: str, message_content: str, connection_id: str, 
                                  authenticated_user: Optional[Dict[str, Any]], conversation_id: Optional[str], task_id: str):
        """异步处理聊天消息"""
        try:
            start_time = asyncio.get_event_loop().time()
            logger.info(f"⚡ 开始处理用户 {user_id} 的消息 (任务ID: {task_id[:8]}...)")
            
            # 使用优化后的handle_stream_chat
            await handle_stream_chat(user_id, message_content, connection_id, authenticated_user, conversation_id)
            
            processing_time = asyncio.get_event_loop().time() - start_time
            self._stats["messages_processed"] += 1
            logger.info(f"✅ 用户 {user_id} 消息处理完成，耗时 {processing_time:.2f}s (任务ID: {task_id[:8]}...)")
            
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"❌ 用户 {user_id} 消息处理失败: {e} (任务ID: {task_id[:8]}...)")
            
            # 发送错误消息
            error_message = WebSocketMessage(
                type=MessageType.AI_ERROR,
                content={"error": "消息处理失败", "details": str(e)},
                sender_id="system",
                receiver_id=None,
                room_id=f"user_{user_id}_room",
                timestamp=datetime.utcnow()
            )
            await self.connection_manager.send_to_connection(connection_id, error_message)
    
    def _cleanup_task(self, task_id: str):
        """清理完成的任务"""
        if task_id in self._processing_tasks:
            del self._processing_tasks[task_id]
            self._stats["active_tasks"] = len(self._processing_tasks)
            logger.debug(f"🧹 清理任务: {task_id[:8]}..., 剩余活跃任务: {self._stats['active_tasks']}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取消息处理统计"""
        return self._stats.copy()
    
    async def handle_switch_conversation(self, connection_id: str, message: WebSocketMessage, authenticated_user: Optional[Dict[str, Any]] = None):
        """处理会话切换消息"""
        logger.info(f"处理会话切换消息: {connection_id}")
        
        # 获取发送者信息
        conn_info = await self.connection_manager.get_connection_info(connection_id)
        if not conn_info or not conn_info.user_info:
            error_message = WebSocketMessage(
                type=MessageType.ERROR,
                content={"error": "未认证用户无法切换会话"},
                sender_id="system",
                receiver_id=None,
                room_id=None,
                timestamp=datetime.utcnow()
            )
            await self.connection_manager.send_to_connection(connection_id, error_message)
            return

        # 获取用户ID和会话ID
        user_id = conn_info.user_info.user_id
        
        # 从消息内容中获取会话ID
        conversation_id = None
        if isinstance(message.content, dict):
            conversation_id = message.content.get("conversation_id")
        elif isinstance(message.content, str):
            conversation_id = message.content
        
        if not conversation_id:
            error_message = WebSocketMessage(
                type=MessageType.ERROR,
                content={"error": "缺少会话ID"},
                sender_id="system",
                receiver_id=None,
                room_id=None,
                timestamp=datetime.utcnow()
            )
            await self.connection_manager.send_to_connection(connection_id, error_message)
            return
        
        # 更新用户会话映射
        user_conversations[user_id] = conversation_id
        logger.info(f"用户 {user_id} 切换到会话 {conversation_id}")
        
        # 发送切换成功消息
        success_message = WebSocketMessage(
            type=MessageType.NOTIFICATION,
            content={
                "message": f"成功切换到会话 {conversation_id}",
                "conversation_id": conversation_id,
                "type": "conversation_switched"
            },
            sender_id="system",
            receiver_id=None,
            room_id=f"user_{user_id}_room",
            timestamp=datetime.utcnow()
        )
        await self.connection_manager.send_to_connection(connection_id, success_message)

# 创建自定义消息处理器
custom_message_handler = CustomMessageHandler(connection_manager)

# =========================
# API端点
# =========================

@websocket_router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: Optional[str] = Query(None, description="用户ID - 必需"),
    username: Optional[str] = Query(None, description="用户名"),
    room_id: Optional[str] = Query(None, description="房间ID"),
    conversation_id: Optional[str] = Query(None, description="会话ID"),
    token: Optional[str] = Query(None, description="JWT令牌")
):
    """
    WebSocket 主端点
    处理 WebSocket 连接和消息
    需要有效的JWT令牌才能建立连接
    """
    # 严格的JWT认证验证 - 强制要求有效令牌
    if not token:
        logger.warning("WebSocket连接被拒绝：缺少JWT令牌")
        await websocket.close(code=4001, reason="连接需要有效的JWT令牌")
        return
    
    # 验证JWT令牌（使用缓存版本）
    authenticated_user = service_manager.verify_token_cached(token)
    if not authenticated_user:
        logger.warning(f"WebSocket连接被拒绝：无效的JWT令牌")
        await websocket.close(code=4001, reason="JWT令牌无效或已过期")
        return
    
    # 额外的令牌有效性检查
    try:
        # 检查令牌是否包含必要的用户信息
        if not authenticated_user.get("user_id"):
            logger.warning("WebSocket连接被拒绝：令牌缺少用户ID")
            await websocket.close(code=4001, reason="令牌缺少必要的用户信息")
            return
        
        # 检查令牌是否过期（额外验证）
        import time
        exp = authenticated_user.get("exp")
        if exp and exp < time.time():
            logger.warning("WebSocket连接被拒绝：令牌已过期")
            await websocket.close(code=4001, reason="JWT令牌已过期")
            return
            
    except Exception as e:
        logger.error(f"WebSocket令牌验证异常: {e}")
        await websocket.close(code=4001, reason="令牌验证失败")
        return
    
    # 确定用户ID
    if not user_id:
        # 如果没有提供用户ID，使用认证用户的ID
        user_id = authenticated_user["user_id"]
    else:
        # 如果提供了用户ID，验证是否与令牌匹配
        if str(user_id) != authenticated_user["user_id"]:
            logger.warning(f"WebSocket连接被拒绝：用户ID不匹配 - 参数:{user_id}, 令牌:{authenticated_user['user_id']}")
            await websocket.close(code=4003, reason="用户ID与令牌不匹配")
            return
    
    # 确保user_id不为None（类型检查）
    if user_id is None:
        logger.error("WebSocket连接被拒绝：无法确定用户ID")
        await websocket.close(code=4001, reason="无法确定用户ID")
        return
    
    # 统一转换为字符串类型，确保类型一致性
    user_id = str(user_id)
    logger.info(f"WebSocket连接用户ID: {user_id} (类型: {type(user_id)})")
    
    connection_id = generate_connection_id()
    
    # 创建用户信息（现在总是有已认证的用户）
    user_info = UserInfo(
        user_id=user_id,
        username=authenticated_user.get("username") or username or f"用户_{user_id}",
        email=authenticated_user.get("email"),
        avatar=None,
        roles=["user"]
    )
    
    # 存储会话ID到全局映射
    if conversation_id:
        user_conversations[user_id] = conversation_id
    
    # 为用户创建单独的房间
    user_room_id = f"user_{user_id}_room"
    
    logger.info(f"新的 WebSocket 连接请求: {connection_id}, 用户: {user_info}, 房间: {user_room_id}")
    
    # 确保性能管理器已初始化
    try:
        await ensure_services_initialized()
    except Exception as e:
        logger.error(f"性能管理器初始化失败: {e}")
        await websocket.close(code=4000, reason="服务初始化失败")
        return
    
    try:
        # 建立新连接（允许同一用户多个连接）
        await connection_manager.connect(
            websocket=websocket,
            connection_id=connection_id,
            user_info=user_info
        )
        
        # 创建或获取用户房间
        from core.web_socket_core.models import RoomInfo
        user_room_info = RoomInfo(
            room_id=user_room_id,
            name=f"用户 {user_id} 的私人空间",
            description="用户专用聊天房间",
            created_by=user_id,
            max_members=5,  # 增加房间容量，允许多次连接
            is_private=True
        )
        
        # 尝试创建房间，如果已存在则忽略
        room_created = await connection_manager.create_room(user_room_info)
        if not room_created:
            logger.info(f"房间已存在，直接加入: {user_room_id}")
        
        # 加入房间
        join_success = await connection_manager.join_room(connection_id, user_room_id)
        if not join_success:
            logger.error(f"加入房间失败: {user_room_id}")
            await websocket.close(code=4002, reason="加入房间失败")
            return
        
        # 发送连接成功消息
        welcome_message = WebSocketMessage(
            type=MessageType.CONNECT,
            content={
                "message": "欢迎使用 AI 个人日常助手！",
                "connection_id": connection_id,
                "user_info": user_info.dict(),
                "room_id": user_room_id,
                "authenticated": True,  # 现在所有连接都需要认证
                "timestamp": datetime.utcnow().isoformat()
            },
            sender_id="system",
            receiver_id=None,
            room_id=user_room_id
        )
        
        await connection_manager.send_to_connection(connection_id, welcome_message)
        
        # 消息处理循环
        while True:
            try:
                # 接收消息
                data = await websocket.receive_text()
                logger.debug(f"收到消息 from {connection_id}: {data}")
                
                # 解析消息
                try:
                    message_data = json.loads(data)
                    
                    # 验证消息格式
                    is_valid, error_msg = validate_message(message_data)
                    if not is_valid:
                        error_response = create_error_message(
                            "INVALID_MESSAGE", 
                            error_msg or "消息格式无效",
                            connection_id
                        )
                        await connection_manager.send_to_connection(
                            connection_id, 
                            error_response
                        )
                        continue
                    
                    # 解析消息
                    message, parse_error = parse_websocket_message(data)
                    if message is None:
                        error_response = create_error_message(
                            "PARSE_ERROR",
                            parse_error or "消息解析失败",
                            connection_id
                        )
                        await connection_manager.send_to_connection(
                            connection_id,
                            error_response
                        )
                        continue
                    
                    # 设置发送者信息和房间ID
                    message.sender_id = user_info.user_id
                    message.room_id = user_room_id
                    
                    # 使用自定义消息处理器处理聊天消息和会话切换消息
                    if message.type == MessageType.CHAT:
                        await custom_message_handler.handle_chat(connection_id, message, authenticated_user)
                    elif message.type == MessageType.SWITCH_CONVERSATION:
                        await custom_message_handler.handle_switch_conversation(connection_id, message, authenticated_user)
                    else:
                        # 其他消息类型使用默认处理器
                        await connection_manager.handle_message(connection_id, message)
                    
                except json.JSONDecodeError:
                    logger.error(f"无效的 JSON 消息: {data}")
                    error_response = create_error_message(
                        "INVALID_JSON",
                        "无效的 JSON 格式",
                        connection_id
                    )
                    await connection_manager.send_to_connection(
                        connection_id,
                        error_response
                    )
                except Exception as e:
                    logger.error(f"处理消息时发生错误: {str(e)}")
                    error_response = create_error_message(
                        "MESSAGE_PROCESSING_ERROR",
                        f"消息处理错误: {str(e)}",
                        connection_id
                    )
                    await connection_manager.send_to_connection(
                        connection_id,
                        error_response
                    )
                    
            except WebSocketDisconnect:
                logger.info(f"WebSocket 连接断开: {connection_id}")
                break
            except Exception as e:
                logger.error(f"WebSocket 错误: {str(e)}")
                break
                
    except Exception as e:
        logger.error(f"WebSocket 连接错误: {str(e)}")
        
    finally:
        # 断开连接
        await connection_manager.disconnect(connection_id)
        logger.info(f"WebSocket 连接已清理: {connection_id}")

# 创建普通API路由器用于其他WebSocket相关的HTTP端点
websocket_http_router = APIRouter(tags=["WebSocket管理"])

@websocket_http_router.post("/broadcast")
async def broadcast_message(
    message_type: str,
    content: str,
    room_id: Optional[str] = None,
    user_id: Optional[str] = None,
    current_user: Dict[str, Any] = CurrentUser
):
    """
    广播消息 API
    用于通过 HTTP 接口发送广播消息
    """
    try:
        # 验证消息类型
        if message_type not in [e.value for e in MessageType]:
            raise HTTPException(status_code=400, detail="无效的消息类型")
        
        # 创建消息
        message = WebSocketMessage(
            type=MessageType(message_type),
            content=content,
            sender_id="system",
            receiver_id=None,
            room_id=None
        )
        
        sent_count = 0
        
        # 根据目标发送消息
        if room_id:
            # 发送到指定房间
            sent_count = await connection_manager.broadcast_to_room(room_id, message)
        elif user_id:
            # 发送到指定用户
            sent_count = await connection_manager.send_to_user(user_id, message)
        else:
            # 广播到所有连接
            sent_count = await connection_manager.broadcast_to_all(message)
        
        return {
            "status": "success",
            "message": "消息发送成功",
            "sent_count": sent_count,
            "message_id": message.id
        }
        
    except Exception as e:
        logger.error(f"广播消息错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"发送消息失败: {str(e)}")


@websocket_http_router.get("/connections")
async def get_connections(current_user: Dict[str, Any] = CurrentUser):
    """获取所有活跃连接信息"""
    connections = []
    for conn_id in connection_manager.active_connections.keys():
        conn_info = await connection_manager.get_connection_info(conn_id)
        if conn_info:
            connections.append(conn_info.dict())
    
    return {
        "total": len(connections),
        "connections": connections
    }


@websocket_http_router.get("/rooms")
async def get_rooms(current_user: Dict[str, Any] = CurrentUser):
    """获取所有房间信息"""
    rooms = []
    for room_id, room_info in connection_manager.rooms.items():
        member_count = len(connection_manager.room_connections.get(room_id, set()))
        rooms.append({
            "room_id": room_id,
            "name": room_info.name,
            "description": room_info.description,
            "member_count": member_count,
            "created_at": room_info.created_at.isoformat(),
            "is_private": room_info.is_private
        })
    
    return {
        "total": len(rooms),
        "rooms": rooms
    }


@websocket_http_router.get("/performance/stats")
async def get_performance_stats(current_user: Dict[str, Any] = CurrentUser):
    """获取性能统计信息"""
    try:
        # 获取性能管理器统计
        perf_stats = performance_manager.get_stats()
        
        # 获取消息处理器统计
        message_handler_stats = custom_message_handler.get_stats()
        
        # 获取service_manager统计
        service_stats = service_manager.get_stats()
        
        # 合并统计信息
        combined_stats = {
            "performance_manager": perf_stats,
            "message_handler": message_handler_stats,
            "service_manager": service_stats,
            "websocket_connections": {
                "total_active": len(connection_manager.active_connections),
                "total_rooms": len(connection_manager.rooms)
            },
            "optimization_status": {
                "graph_runtime_ready": aide_runtime.is_ready(),
                "tools_loaded": aide_runtime.tool_count(),
                "session_manager_cache": len(performance_manager._session_managers) > 0,
                "async_message_processing": True
            }
        }
        
        return {
            "status": "success",
            "data": combined_stats
        }
        
    except Exception as e:
        logger.error(f"获取性能统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取性能统计失败: {str(e)}")


@websocket_http_router.post("/performance/cleanup")
async def cleanup_expired_caches(current_user: Dict[str, Any] = CurrentUser):
    """清理过期缓存"""
    try:
        # 清理性能管理器的过期缓存
        performance_manager.cleanup_expired_caches()
        
        # 清理service_manager的过期缓存
        service_manager.clear_expired_cache()
        
        return {
            "status": "success",
            "message": "过期缓存已清理"
        }
        
    except Exception as e:
        logger.error(f"清理过期缓存失败: {e}")
        raise HTTPException(status_code=500, detail=f"清理过期缓存失败: {str(e)}")


@websocket_http_router.post("/performance/refresh_user_context/{user_id}")
async def refresh_user_context(user_id: int, current_user: Dict[str, Any] = CurrentUser):
    """按当前库里的数据重算一份用户上下文

    旧引擎给上下文做了带 TTL 的缓存，这里顺带当"强制刷新"入口；LangGraph 每轮都
    现取上下文，缓存已随之取消，本接口只用于核对偏好是否已生效。
    """
    try:
        context = build_user_context(user_id)
        return {
            "status": "success",
            "message": f"用户 {user_id} 的上下文已重新装配",
            "user_context": {
                "user_id": context.user_id,
                "user_name": context.user_name,
                "city": context.city,
                "preferences_count": len(context.preferences),
            }
        }
    except Exception as e:
        logger.error(f"刷新用户 {user_id} 上下文失败: {e}")
        raise HTTPException(status_code=500, detail=f"刷新用户上下文失败: {str(e)}")

# 导出路由器
websocket_router.include_router(websocket_http_router) 