基于OpenAI Agents SDK的多智能体个人日常助手系统
开发⼈员
项目描述：构建一个基于多智能体协作的个人日常助手系统，集成MCP协议实现标准化工具调用与RAG知识检索，
支持天气查询、新闻获取、菜谱推荐、笔记/待办管理等功能，通过WebSocket实现实时双向通信。
项目实现：
·采用OpenAI Agents SDK构建Hub-and-Spoke多智能体架构：Triage Agent作为任务调度中心，按用户意图动态
路由至Weather/News/Recipe/Personal Assistant四个专职Agent，各Agent独立配置Instructions与工具集。
·基于FastMCP实现MCP Server，将外部API封装为标准MCP工具，按Agent名称前缀动态过滤工具可见性（如
Weather Agent仅可见weather_*工具）。MCP Server作为独立子进程运行，主应用通过asyncio子进程管理其
生命周期。
·RAG采用ChromaDB向量数据库，按用户ID隔离Collection，嵌入层使用OpenAI text-embedding-3-small模型。
NoteService将笔记内容向量化存储，支持语义搜索与元数据过滤混合检索。
·前端基于React+TypeScript+Vite构建，使用Tailwind CSS+shadcn/ui组件库。通过WebSocket实现Agent状态
实时推送，支持多会话管理、对话历史持久化与恢复。
·后端基于FastAPI，采用服务管理器模式统一管理DatabaseClient、ChromaVectorClient等组件的生命周期。
实现了完整的REST API体系（认证/管理/会话/笔记/待办）和WebSocket房间广播机制（含心跳检测与超时
清理）。
·接入三类免费外部API：Open-Meteo天气（无需API Key）、TheMealDB菜谱（完全免费）、The News API新闻
（免费额度），均通过Pydantic模型层封装请求/响应。
遇到的问题：MCP Server作为独立进程需与主应用协调生命周期，进程异常退出时Agent的工具调用会全部失败。
解决方案是在FastAPI的lifespan中通过asyncio.create_subprocess_exec启动子进程，注册signal handler和
shutdown hook确保优雅关闭，同时Agent端做工具调用失败的降级处理。
技术栈：OpenAI Agents SDK、FastMCP、FastAPI、ChromaDB、React、TypeScript、WebSocket、Tailwind CSS、MySQL
