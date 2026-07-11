"""
AI 个人日常助手 - 主应用入口

重构后的干净整洁的主应用文件，统一管理所有API模块
"""

import asyncio
import logging
import subprocess
import sys
import os
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 导入所有API路由器
from api import (
    auth_router,
    admin_router,
    conversation_router,
    websocket_router,
    system_router,
    note_router,
    todo_router
)

# 导入WebSocket核心模块
from core.web_socket_core import connection_manager, WebSocketConfig

# 导入服务管理器
from service.service_manager import service_manager

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# 全局变量 - MCP服务器进程管理
# =========================
mcp_server_process = None

# =========================
# MCP服务器进程管理函数
# =========================
async def start_mcp_server():
    """启动MCP服务器进程"""
    global mcp_server_process
    
    try:
        print("🔌 正在启动MCP服务器进程...")
        
        # 获取mcp_server.py的路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        mcp_server_path = os.path.join(current_dir, "mcp-serve", "mcp_server.py")
        
        # 启动子进程
        mcp_server_process = await asyncio.create_subprocess_exec(
            sys.executable, mcp_server_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=current_dir
        )
        
        print(f"✅ MCP服务器进程已启动 (PID: {mcp_server_process.pid})")
        
        # 启动后台任务监控MCP服务器输出
        asyncio.create_task(monitor_mcp_server_output())
        
        return True
        
    except Exception as e:
        print(f"❌ 启动MCP服务器进程失败: {e}")
        return False

async def stop_mcp_server():
    """停止MCP服务器进程"""
    global mcp_server_process
    
    if mcp_server_process:
        try:
            print("🛑 正在停止MCP服务器进程...")
            
            # 发送终止信号
            mcp_server_process.terminate()
            
            # 等待进程结束，最多等待10秒
            try:
                await asyncio.wait_for(mcp_server_process.wait(), timeout=10.0)
                print("✅ MCP服务器进程已正常停止")
            except asyncio.TimeoutError:
                print("⚠️  MCP服务器进程未在规定时间内停止，强制终止...")
                mcp_server_process.kill()
                await mcp_server_process.wait()
                print("✅ MCP服务器进程已强制停止")
                
        except Exception as e:
            print(f"❌ 停止MCP服务器进程时发生错误: {e}")
        finally:
            mcp_server_process = None

async def monitor_mcp_server_output():
    """监控MCP服务器进程的输出"""
    global mcp_server_process
    
    if not mcp_server_process or not mcp_server_process.stdout:
        return
    
    try:
        # 监控stdout
        while True:
            line = await mcp_server_process.stdout.readline()
            if not line:
                break
            # 将MCP服务器的输出添加前缀后打印
            print(f"[MCP] {line.decode().strip()}")
            
    except Exception as e:
        logger.error(f"监控MCP服务器输出时发生错误: {e}")

# =========================
# 初始化函数（从原文件移过来的）
# =========================
async def initialize_all_services():
    """初始化所有服务（优化版本）"""
    try:
        print("🚀 开始初始化所有服务...")
        
        # 1. 先启动MCP服务器
        print("🔌 正在启动MCP服务器...")
        mcp_started = await start_mcp_server()
        if mcp_started:
            print("✅ MCP服务器启动完成")
            # 给MCP服务器一些时间完成初始化
            await asyncio.sleep(2)
        else:
            print("⚠️  MCP服务器启动失败，主应用将继续运行")
        
        # 2. 初始化服务管理器
        print("⚙️  正在初始化服务管理器...")
        if not service_manager.initialize():
            raise Exception("服务管理器初始化失败")
        print("✅ 服务管理器初始化完成")
        
        print("🎉 所有服务初始化完成")
            
    except Exception as e:
        print(f"❌ 服务初始化失败: {e}")
        print("⚠️  应用将在有限功能下继续运行")

async def periodic_cache_cleanup():
    """定期清理过期缓存的后台任务"""
    while True:
        try:
            # 每30分钟清理一次过期缓存
            await asyncio.sleep(1800)  # 30分钟
            service_manager.clear_expired_cache()
            logger.info("定期清理过期缓存完成")
        except asyncio.CancelledError:
            logger.info("缓存清理任务已停止")
            break
        except Exception as e:
            logger.error(f"定期清理过期缓存失败: {e}")
            # 如果出错，等待10分钟后重试
            await asyncio.sleep(600)

# =========================
# 应用生命周期管理
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时的初始化
    logger.info("启动 AI 个人日常助手服务...")
    
    # 初始化所有服务（包括MCP服务器）
    await initialize_all_services()
    
    # 启动心跳检测任务
    if not connection_manager.heartbeat_task:
        connection_manager.heartbeat_task = asyncio.create_task(
            connection_manager._heartbeat_loop()
        )
    
    # 启动定期缓存清理任务
    cache_cleanup_task = asyncio.create_task(periodic_cache_cleanup())
    
    logger.info("✅ AI 个人日常助手服务已启动")
    
    yield
    
    # 关闭时的清理
    logger.info("关闭 AI 个人日常助手服务...")
    
    # 先停止MCP服务器进程
    await stop_mcp_server()
    
    # 停止心跳检测任务
    if connection_manager.heartbeat_task:
        connection_manager.heartbeat_task.cancel()
        try:
            await connection_manager.heartbeat_task
        except asyncio.CancelledError:
            pass
    
    # 停止缓存清理任务
    cache_cleanup_task.cancel()
    try:
        await cache_cleanup_task
    except asyncio.CancelledError:
        pass
    
    # 关闭服务管理器（统一关闭所有服务）
    try:
        service_manager.close()
        logger.info("✅ 服务管理器已关闭")
    except Exception as service_cleanup_error:
        logger.error(f"⚠️  关闭服务管理器时发生错误: {service_cleanup_error}")
    
    logger.info("✅ AI 个人日常助手服务已关闭")

# =========================
# 创建 FastAPI 应用
# =========================
app = FastAPI(
    title="AI 个人日常助手服务",
    description="提供认证、会话管理、WebSocket通信等功能的智能助手服务",
    version="1.0.0",
    lifespan=lifespan
)

# =========================
# 添加中间件
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# 静态文件服务配置
# =========================

# 检查静态文件目录是否存在
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    # 挂载静态文件服务
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    
    # 为前端应用添加根路径处理
    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        """提供前端应用的主页面"""
        index_file = os.path.join(static_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        else:
            return {"message": "AI 个人日常助手 API 服务", "static_files": "前端文件未找到"}
    
# =========================
# 注册所有路由器
# =========================

# 系统路由器（API路径）
app.include_router(system_router, prefix="/api")

# 认证路由器
app.include_router(auth_router, prefix="/api")

# 管理员路由器
app.include_router(admin_router, prefix="/api")

# 会话路由器
app.include_router(conversation_router, prefix="/api")

# 笔记路由器
app.include_router(note_router, prefix="/api")

# 待办事项路由器
app.include_router(todo_router, prefix="/api")

# WebSocket路由器（包含所有WebSocket相关端点）
app.include_router(websocket_router)

# 为前端路由添加回退处理（支持单页应用路由）
# 注意：这个路由必须在所有API路由注册之后，以避免拦截API请求
@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend_routes(full_path: str):
    """为前端单页应用提供路由回退"""
    # 检查是否存在对应的静态文件
    file_path = os.path.join(static_dir, full_path)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    
    # 对于非API路径，返回index.html（单页应用路由）
    # 这样前端路由（如 /dashboard, /login 等）会正确显示
    if not full_path.startswith("api/") and not full_path.startswith("ws"):
        index_file = os.path.join(static_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
    
    # 如果是API路径但没有匹配的处理器，返回404
    return {"error": "路径未找到"}

# =========================
# 主程序入口
# =========================
if __name__ == "__main__":
    import uvicorn
    
    # 启动服务器
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=WebSocketConfig.DEFAULT_PORT,
        log_level="info",
        reload=False
    ) 