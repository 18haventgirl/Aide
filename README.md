# Aide — 智能个人日常助手

一个基于 Python 后端和 React 前端的多智能体个人日常助手，集成 MCP 协议与 RAG 知识检索，帮助用户管理日常任务、笔记、对话，并提供智能化服务。

## 项目结构 (Project Structure)

```
ai-personal-daily-assistant/
├── backend/                          # Python 后端服务 (Python backend service)
│   ├── agent/                       # AI 代理模块 (AI agent modules)
│   │   ├── agent_session.py         # 代理会话管理
│   │   ├── example_usage.py         # 使用示例
│   │   ├── personal_assistant_manager.py  # 个人助手管理器
│   │   └── personal_assistant.py    # 个人助手核心
│   ├── api/                         # API 接口 (API endpoints)
│   │   ├── admin_api.py             # 管理员接口
│   │   ├── auth_api.py              # 认证接口
│   │   ├── conversation_api.py      # 对话接口
│   │   ├── note_api.py              # 笔记接口
│   │   ├── system_api.py            # 系统接口
│   │   ├── todo_api.py              # 待办事项接口
│   │   └── websocket_api.py         # WebSocket 接口
│   ├── core/                        # 核心功能模块 (Core functionality)
│   │   ├── auth_core/               # 认证核心
│   │   ├── database_core/           # 数据库核心
│   │   ├── http_core/               # HTTP 核心
│   │   ├── vector_core/             # 向量数据库核心
│   │   ├── web_socket_core/         # WebSocket 核心
│   │   └── performance_manager.py   # 性能管理器
│   ├── mcp-serve/                   # MCP 服务 (MCP Services)
│   │   ├── mcp_server.py            # MCP 服务器
│   │   ├── news_tools.py            # 新闻工具
│   │   ├── recipe_tools.py          # 食谱工具
│   │   ├── user_data_tools.py       # 用户数据工具
│   │   └── weather_tools.py         # 天气工具
│   ├── remote_api/                  # 远程 API 客户端 (Remote API clients)
│   │   ├── jsonplaceholder/         # JSON Placeholder API
│   │   ├── news/                    # 新闻 API
│   │   ├── recipe/                  # 食谱 API
│   │   └── weather/                 # 天气 API
│   ├── service/                     # 业务服务层 (Business service layer)
│   │   ├── models/                  # 数据模型
│   │   ├── services/                # 具体服务实现
│   │   └── service_manager.py       # 服务管理器
│   ├── main.py                      # 主入口文件 (Main entry point)
│   ├── requirements.txt             # Python 依赖包
│   └── env.example                  # 环境变量示例文件
├── ui/                              # 前端界面 (Frontend UI - React)
│   ├── src/                         # 源代码目录
│   │   ├── components/              # React 组件
│   │   │   ├── ui/                  # UI 基础组件
│   │   │   ├── Chat.tsx             # 聊天组件
│   │   │   ├── ConversationList.tsx # 对话列表
│   │   │   ├── notes-panel.tsx      # 笔记面板
│   │   │   ├── todos-panel.tsx      # 待办事项面板
│   │   │   └── ...                  # 其他组件
│   │   ├── pages/                   # 页面组件
│   │   │   ├── Dashboard.tsx        # 仪表板页面
│   │   │   └── Login.tsx            # 登录页面
│   │   ├── hooks/                   # React Hooks
│   │   ├── lib/                     # 工具库
│   │   ├── services/                # 前端服务
│   │   ├── store/                   # 状态管理
│   │   └── main.tsx                 # 入口文件
│   ├── package.json                 # Node.js 依赖配置
│   ├── vite.config.ts               # Vite 配置文件
│   └── tailwind.config.js           # Tailwind CSS 配置
└── README.md                        # 项目说明文档
```

## 后端环境配置与运行 (Backend Environment Setup & Running)

### 前置要求 (Prerequisites)

- Python 3.8+
- pip (Python 包管理器)
- PostgreSQL 数据库 (或其他支持的数据库)
- ChromaDB (向量数据库，如使用远程端则需要 C++ 编译环境)

### 1. 创建虚拟环境 (Create Virtual Environment)

```bash
# 在项目根目录下创建虚拟环境 (Create virtual environment in project root)
python -m venv venv

# 或者使用 python3 (Or use python3)
python3 -m venv venv
```

### 2. 激活虚拟环境 (Activate Virtual Environment)

**macOS/Linux:**
```bash
source venv/bin/activate
```

**Windows:**
```bash
# PowerShell
venv\Scripts\Activate.ps1

# 命令提示符 (Command Prompt)
venv\Scripts\activate.bat
```

### 3. 安装后端依赖 (Install Backend Dependencies)

```bash
# 进入后端目录 (Navigate to backend directory)
cd backend

# 安装依赖包 (Install required packages)
pip install -r requirements.txt
```

### 4. 配置环境变量 (Configure Environment Variables)

在 `backend` 目录下创建 `.env` 文件：

```bash
# 复制示例文件 (Copy example file)
cp env.example .env
```

在 `.env` 文件中配置以下环境变量：

```env
# OpenAI API 配置 (OpenAI API Configuration)
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_CHAT_MODEL=gpt-4
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# 新闻 API 配置 (News API Configuration)
NEWS_API_TOKEN=your_news_api_token_here

# 数据库配置 (Database Configuration)
DB_HOST=localhost
DB_PORT=5432
DB_USERNAME=your_username
DB_PASSWORD=your_password
DB_DATABASE=ai_assistant
DB_CHARSET=utf8mb4

# ChromaDB 向量数据库配置 (ChromaDB Vector Database Configuration)
# 注意：使用远程 CHROMA 端点时，本地需要安装 C++ 编译环境
# Note: When using remote CHROMA endpoint, local C++ compilation environment is required
CHROMA_CLIENT_MODE=remote  # 可选值: local, remote
CHROMA_HOST=localhost
CHROMA_PORT=8000
```

### 5. 数据库初始化 (Database Initialization)

```bash
# 确保数据库服务正在运行，然后执行数据库初始化
python -c "from core.database_core.init_db import init_database; init_database()"
```

### 6. 运行后端服务 (Run Backend Service)

```bash
# 确保在 backend 目录下 (Make sure you are in the backend directory)
cd backend

# 运行后端服务 (Run backend service)
python main.py
```

后端服务默认运行在 `http://localhost:8000`

## 前端环境配置与运行 (Frontend Environment Setup & Running)

### 前置要求 (Prerequisites)

- Node.js 16+
- npm 或 yarn

### 1. 安装前端依赖 (Install Frontend Dependencies)

```bash
# 进入前端目录 (Navigate to frontend directory)
cd ui

# 安装依赖 (Install dependencies)
npm install

# 或使用 yarn (Or use yarn)
yarn install
```

### 2. 配置前端环境 (Configure Frontend Environment)

在 `ui` 目录下创建 `.env` 文件（如果需要）：

```env
# API 基础地址 (API Base URL)
VITE_API_BASE_URL=http://localhost:8000

# WebSocket 地址 (WebSocket URL)
VITE_WS_URL=ws://localhost:8000/ws
```

### 3. 运行前端开发服务器 (Run Frontend Development Server)

```bash
# 确保在 ui 目录下 (Make sure you are in the ui directory)
cd ui

# 启动开发服务器 (Start development server)
npm run dev

# 或使用 yarn (Or use yarn)
yarn dev
```

前端开发服务器默认运行在 `http://localhost:5173`

### 4. 构建生产版本 (Build for Production)

```bash
# 构建生产版本 (Build for production)
npm run build

# 预览构建结果 (Preview build)
npm run preview
```

## 开发注意事项 (Development Notes)

1. **ChromaDB 配置**: 本服务使用远程 ChromaDB，如果使用本地环境已安装 C++ 编译工具
2. **API 密钥**: 请确保所有必需的 API 密钥都已正确配置
3. **数据库连接**: 确保数据库服务正在运行并且连接信息正确
4. **端口冲突**: 如果默认端口被占用，请在配置文件中修改端口设置

## 功能特性 (Features)

- 🤖 AI 智能对话助手
- 📝 智能笔记管理
- ✅ 待办事项管理
- 🌤️ 天气信息查询
- 📰 新闻资讯获取
- 🍳 食谱推荐
- 🔍 向量化语义搜索
- 💬 实时 WebSocket 通信
- 🔐 用户认证与授权

## API 文档 (API Documentation)

启动后端服务后，访问 `http://localhost:8000/docs` 查看完整的 API 文档。

## 技术栈 (Tech Stack)

**后端 (Backend):**
- Python 3.8+
- FastAPI
- SQLAlchemy
- PostgreSQL
- ChromaDB
- OpenAI API

**前端 (Frontend):**
- React 18
- TypeScript
- Vite
- Tailwind CSS
- Redux Toolkit