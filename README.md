# lg-aide — 智能个人日常助手（dev/lg 改造线）

一个基于 Python 后端和 React 前端的多智能体个人日常助手，集成 MCP 协议与 RAG 知识检索，帮助用户管理日常任务、笔记、对话，并提供智能化服务。

> 本分支（`dev/lg`）与原 Aide 实例并行开发，凡是能在宿主机上留下痕迹的名字都带 `lg` / `lg-aide` 前缀：Docker 容器与数据卷、MySQL 库名与账号、Chroma 集合前缀、npm 包名、FastAPI 文档标题，端口也整体挪到 8100/8102/8101/3307/5199。这样两个实例同时运行不会抢端口、抢容器名，也不会读到对方的数据。

## 项目结构 (Project Structure)

```
lg-aide/
├── backend/                          # Python 后端服务 (Python backend service)
│   ├── agent/                       # AI 代理模块 (AI agent modules)
│   │   ├── agent_session.py         # 代理会话管理
│   │   ├── guardrails.py            # 输入护栏：安全性 + 相关性检查
│   │   └── personal_assistant_manager.py  # 多代理装配与用户上下文
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
│   │   ├── runtime_config.py        # 端口 / 地址 / CORS 集中配置
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
│   ├── tests/                       # pytest 冒烟测试（不依赖外部服务）
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

- Python 3.9+（开发与验证均在 3.11 上进行）
- pip (Python 包管理器)
- MySQL 8 —— 依赖数据库，`docker compose up -d mysql` 会在宿主机 3307 端口起一个
- ChromaDB —— `docker compose up -d chromadb`（宿主机 8101），或设 `CHROMA_CLIENT_MODE=local` 走进程内持久化，不需要外部服务
- 一个 OpenAI 兼容的 API Key（对话与向量化都依赖它）

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

全部可配置项都已写在 `backend/env.example` 里（含默认端口），复制后至少填这三个：

```env
OPENAI_API_KEY=your_openai_api_key_here
NEWS_API_TOKEN=your_news_api_token_here
JWT_SECRET_KEY=change-me   # python -c "import secrets; print(secrets.token_urlsafe(48))"
```

端口一览（均可用同名环境变量覆盖，定义见 `backend/core/runtime_config.py`）：

| 服务 | 环境变量 | 默认 |
| --- | --- | --- |
| 后端 API + WebSocket | `API_PORT` | 8100 |
| MCP 工具服务 | `MCP_PORT` | 8102 |
| ChromaDB | `CHROMA_PORT` | 8101 |
| MySQL（宿主机映射） | `DB_PORT` | 3307 |
| 前端开发服务器 | `UI_PORT` | 5199 |

### 5. 启动依赖服务 (Start Dependencies)

```bash
# 在项目根目录，只起 MySQL 与 ChromaDB，后端/前端仍在宿主机运行
docker compose up -d
```

不想用 Docker 时，跳过本步并把向量库改为进程内模式：`CHROMA_CLIENT_MODE=local`（需自备 MySQL，或只测试不依赖数据库的接口）。

### 5.1 本地向量化 (Local Embeddings)

笔记语义检索需要 embedding 能力，而 DeepSeek 这类对话网关不提供 `/embeddings`。默认改用
进程内的本地模型 `BAAI/bge-small-zh-v1.5`（512 维，约 95MB，CPU 上加载 0.3 秒），
不依赖外网也不需要额外密钥。模型权重不入库，需要自己下载到 `backend/models/`：

```bash
# 在 backend 目录下
mkdir -p models/bge-small-zh-v1.5/1_Pooling && cd models/bge-small-zh-v1.5
BASE="https://www.modelscope.cn/api/v1/models/BAAI/bge-small-zh-v1.5/repo?Revision=master&FilePath="
for f in config.json config_sentence_transformers.json sentence_bert_config.json \
         tokenizer.json tokenizer_config.json special_tokens_map.json vocab.txt \
         modules.json 1_Pooling/config.json model.safetensors; do
  curl -sL -o "$f" "${BASE}${f}"     # -L 必须加：大文件会 302 到 CDN
done

# 如果你的网络能直连 huggingface.co，也可以不下载，直接把 .env 改成：
#   LOCAL_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
```

要换回远端 embeddings：`.env` 里设 `EMBEDDING_PROVIDER=openai` 并给一个能调 OpenAI
embeddings 的 key（`EMBEDDING_OPENAI_API_KEY`，不设则回落到 `OPENAI_API_KEY`），
同时把 `VECTOR_DIMENSION` 改回 1536。

> 换 embedding 模型等于换向量空间，旧的 `CHROMA_PERSIST_DIR` 目录必须删掉重建，
> 否则维度不一致会让检索直接失败；已有笔记需要重新写入向量库才能被搜到。

### 6. 数据库初始化 (Database Initialization)

```bash
# 确保数据库服务正在运行，然后执行数据库初始化
python -m core.database_core.init_db
```

### 7. 运行后端服务 (Run Backend Service)

```bash
# 确保在 backend 目录下 (Make sure you are in the backend directory)
cd backend

# 运行后端服务 (Run backend service)
python main.py
```

后端服务默认运行在 `http://localhost:8100`，MCP 工具服务由它作为子进程拉起并监听 `http://127.0.0.1:8102/mcp`

### 8. 运行冒烟测试 (Run Smoke Tests)

```bash
# 仍在 backend 目录、同一个虚拟环境中（pytest 已在 requirements.txt 的测试依赖段里）
pip install -r requirements.txt
pytest tests
```

`tests/` 只覆盖端口配置、输入护栏装配和 WebSocket 消息工具这类纯逻辑，不需要 MySQL、ChromaDB 或真实 API Key。

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

默认无需任何配置：前端所有请求都走同源相对路径（`/api`、`/ws`），由 Vite 代理转发到 `http://localhost:8100`（见 `ui/vite.config.ts`）。

需要改端口或让浏览器绕过代理直连后端时，在 `ui` 目录下创建 `.env` 文件：

```env
# 前端开发服务器端口；改了它，后端 CORS_ORIGINS 也要包含同一个来源
UI_PORT=5199
# Vite 代理转发的后端地址
VITE_API_TARGET=http://localhost:8100
# API 基础地址；只在浏览器绕过代理直连后端时才需要设置，默认同源
VITE_API_BASE_URL=http://localhost:8100
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

前端开发服务器默认运行在 `http://localhost:5199`

### 4. 构建生产版本 (Build for Production)

```bash
# 构建生产版本 (Build for production)
npm run build

# 预览构建结果 (Preview build)
npm run preview
```

## 开发注意事项 (Development Notes)

1. **ChromaDB 配置**: 默认以 HTTP 客户端连接 `CHROMA_HOST:CHROMA_PORT`（docker-compose 在宿主机 8101 提供）；设 `CHROMA_CLIENT_MODE=local` 可退回进程内持久化，数据落在 `CHROMA_PERSIST_DIR`
2. **API 密钥**: `OPENAI_API_KEY`（对话 + 向量化）与 `NEWS_API_TOKEN` 必填；天气（Open-Meteo）与菜谱（TheMealDB）不需要密钥
3. **数据库连接**: 表结构在后端启动时由 `service_manager.initialize()` 自动创建，无需手工建表
4. **端口冲突**: 端口全部来自环境变量（`API_PORT` / `MCP_PORT` / `CHROMA_PORT` / `DB_PORT` / `UI_PORT`），改配置即可，不需要动代码
5. **跨域**: 后端不再放开 `*`。换了前端端口或域名时，同步设置 `CORS_ORIGINS`

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

启动后端服务后，访问 `http://localhost:8100/docs` 查看完整的 API 文档。

## 技术栈 (Tech Stack)

**后端 (Backend):**
- Python 3.9+（验证环境 3.11）
- FastAPI + Uvicorn
- SQLAlchemy 2 + PyMySQL
- MySQL 8
- ChromaDB（向量检索 / RAG）
- OpenAI Agents SDK + LiteLLM
- MCP（fastmcp，Streamable HTTP 传输）

**前端 (Frontend):**
- React 19
- TypeScript
- Vite
- Tailwind CSS
- Redux Toolkit