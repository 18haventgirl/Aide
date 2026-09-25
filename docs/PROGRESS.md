# LG-Aide 工作日志

> 目的：把"已经核实的事实"和"当前进度"写在一个地方，避免跨会话凭记忆推断。
> 规则：每完成一个阶段就更新本文件；**只有实测过的结论才写进来**，推测写在"待验证"。

## 环境事实（实测）

| 项 | 值 |
| --- | --- |
| 工作区 | `D:\Workplace\AIDE-LG\Aide`（分支 `dev/lg`，远端 `origin/dev/lg`） |
| 另一个实例 | `D:\Workplace\Aide`，仍用原端口，**禁止跨目录改动** |
| 后端环境 | conda `lg-aide`（Python 3.11），`C:\Users\HONOR\.conda\envs\lg-aide\python.exe` |
| 一次性调研环境 | conda `lg-langgraph-spike`，LangGraph 迁移调研用，**结束后删除** |
| 依赖安装 | `uv pip install --python <上面那个 python.exe> --index-url https://pypi.tuna.tsinghua.edu.cn/simple --only-binary :all:`（pip 原生解析会在 litellm 上疯狂回溯） |
| 端口 | API 8100 · MCP 8102 · Chroma 8101 · MySQL 3307 · 前端 5199 |
| 依赖服务 | `docker compose up -d mysql` → 容器 `lg-aide-mysql`；向量库用本地模式（`CHROMA_CLIENT_MODE=local`，目录 `backend/lg-aide-chroma-db/`） |
| 模型 | DeepSeek，`OPENAI_API_BASE_URL=https://api.deepseek.com`；chat 模型名 litellm 写法是 `openai/deepseek-chat`，**LangChain 下要写 `deepseek-chat`** |
| 向量化 | 本地 `backend/models/bge-small-zh-v1.5`（512 维，huggingface 不通，只能走 ModelScope，见 README 5.1） |
| 测试账号 | `lguser`(id1) / `short`(id2) / `uixuser`(id3) / `freshuser`(id13)，密码统一见 `backend/.env` 之外的口头交代，**不写进仓库** |
| 启动 | 后端 `python -m uvicorn main:app --host 127.0.0.1 --port 8100`（cwd=backend，启动约需 60s：要加载 embedding 模型）；前端 `npm run dev` |

## 已完成并推送的部分

`origin/dev/lg` 上：`master(9b69d34)` → 4 个提交，用户已验收"完美"。

| SHA | 内容 |
| --- | --- |
| `af9cba8` | 端口/CORS/依赖/文档集中化；MCP 子进程 GBK 崩溃与 stderr 管道卡死修复；docker-compose |
| `c8d5e0b` | 输入护栏接入真实执行链（Triage）；清除死代码（净 −2887 行）；27 项 pytest |
| `e1f7ae1` | 真账号体系（users 表/注册/bcrypt）、标签自由化、本地向量检索 + cosine/阈值修正、`/api/health` 真实探测 |
| `306312d` | 删除前端演示残留 `lib/api.ts`、`lib/mockData.ts` |

这一版是当前**回退锚点**：LangGraph 迁移出问题就回到 `306312d`。

期间修掉的隐蔽缺陷（都有实测证据）：`load_dotenv` 时机导致 JWT 静默用公开默认密钥；`AuthService.verify_token ↔ service_manager.verify_token_cached` 无限递归导致全部鉴权接口 401；passlib 1.7.4 与 bcrypt 5.x 不兼容；Chroma 默认 l2 距离被当余弦用 + 阈值 0.7 导致语义检索长期无效；`UserService` 依赖公共演示站导致 id≥11 的账号被判"不存在"。

## 当前任务：OpenAI Agents SDK → LangGraph

- 设计已批准并落盘：`docs/superpowers/specs/2026-09-26-langgraph-migration-design.md`
- 已确认决策：一步硬切 / 单 agent + 工具图 / AsyncSqliteSaver 与 MySQL 并存（checkpoint 为对话真相，MySQL 为展示副本）/ 先验证 RAG 再接工具 / 面板改为图执行轨迹 + 工具清单 / `langchain-openai` 直连 / 验收 = 端到端脚本 + pytest 集成
- SDK 耦合面（实测）：只有 4 个文件引用 `agents` —— `agent/personal_assistant_manager.py`(32) `api/websocket_api.py`(16) `agent/guardrails.py`(2) `tests/test_guardrails.py`(3)；业务层与框架无关
- 实测到的 LangGraph 生态版本与 API 形状见 spec 第 2 节（`create_agent` 参数、`AgentMiddleware` 钩子、内置 middleware、`MultiServerMCPClient(tool_name_prefix=)`、`AsyncSqliteSaver`）

阶段划分：0 RAG 召回验证 → 1 引擎骨架 → 2 流式与事件 → 3 前端面板 → 4 收尾与回归。

### 进度

- [x] 阶段 0：`tests/test_rag_recall.py` 离线召回验证（5 文档 / 8 组查询，top-3 命中、更新后相关性反转、删除后不出索引）
- [x] 阶段 1：`context.py` / `graph.py` / `middleware.py` / `tools/notes.py` / `tools/mcp.py` / 依赖增删 / 非流式 `runtime.ask()`
  - 提交：`8a40f9c` 依赖与模型构造 → `c3386af` UserContext → `1a24f73` 护栏中间件 → `64db30c` RAG+MCP 工具 → `699c1ec` 建图与运行时 → `f213815` 护栏重复判定修复
  - 全量 `pytest tests -q`：**64 passed**（其中新增 agent/middleware/tools/graph 用例 31 个），全程离线可跑
  - 非流式冒烟（真实 DeepSeek + 本地 MCP）：`ask(3,'smoke-1','明天上海天气怎么样？')` → 护栏放行 → 模型自己填出上海经纬度 → `weather_get_daily_weather_forecast` 返回真实预报 → 中文结论式回答，`error=None`
- [ ] 阶段 2：`astream` 流式 + WS 事件翻译 + checkpoint 落地
- [ ] 阶段 3：前端图执行轨迹与工具清单
- [ ] 阶段 4：删除旧引擎、文档、全量回归

### 阶段 1 落地的三条硬规则（后续改动不要破坏）

1. **身份不接受模型填写**：MCP 的 11 个 `user_data_*` 工具入参带 `user_id`，`build_identity_middleware()`（`wrap_tool_call`）在真正执行前用 `runtime.context.user_id` 覆写并 WARNING。本地 RAG 工具压根没有 `user_id` 入参，身份只从 context 取。
2. **护栏每轮只判一次**：`before_model` 在工具回环里会再次触发，`_resuming_after_tool()` 检测最后一条是 `ToolMessage` 时直接返回 `None`。否则同句话判两遍：多两次 LLM 往返、面板重复行，且第二遍会把模型自己的回答当成判定结论。
3. **工具异常必须变成字符串**：`search_my_notes`/`save_note` 对"服务不可用/无上下文/无命中/向量库挂了"都返回中文句子，其中向量检索失败会回退关键词检索；`load_mcp_tools()` 连不上返回 `[]`，对话继续只是没外部工具。


## 待验证（不许当作事实使用）

1. ~~`create_agent` 的 `context_schema` 如何把 `UserContext` 注入工具~~ **已实测（阶段 1）**：工具签名写 `runtime: ToolRuntime[UserContext] = None` 即可，`langchain.tools` 有再导出（实际定义在 `langgraph.prebuilt.tool_node`）；该参数会被自动排除在 `tool_call_schema` 之外，模型看不到也填不了。单独 `tool.ainvoke({...})` 时 `runtime` 为 `None`，显式传 `runtime=None` 反而被 pydantic 拒（类型是 dataclass），要省略键。
2. `stream_mode=["messages","updates"]` 同时开启时的产出形状——阶段 2 spike
3. `AsyncSqliteSaver` 在 uvicorn 并发下的文件锁表现——阶段 2 spike
4. ~~`tool_name_prefix=True` 产出的工具名~~ **已实测（阶段 1）**：用 `tool_name_prefix=False`，29 个工具名原样为 `weather_/news_/recipe_/user_data_` 前缀，与 MCP 服务端一致；`load_mcp_tools()` 对运行中的 8102 真实返回 29 个。
5. 单 agent 挂 29+2 工具时 DeepSeek 的工具选择准确率与 token 成本——阶段 2 实测（首个冒烟选对了天气工具）
6. 会话标题生成改为每轮后一次独立小调用，效果是否够用——阶段 4
7. **新发现，待阶段 2 处理**：MCP 工具的 `ToolMessage.content` 不是纯文本，而是 `[{'type': 'text', 'text': '<json 字符串>'}]` 列表；直接 `str(m.content)` 会把 Python repr 灌给模型和面板，翻译层要取 `part["text"]` 再裁剪。
8. **新发现，遗留风险**：MCP 侧 `user_data_update_note / delete_note / update_todo / complete_todo / delete_todo` 只按 `note_id/todo_id` 定位记录，服务端不校验归属，所以"猜别人的 id 改别人的数据"这条路径仍然开着——身份覆写只挡得住带 `user_id` 入参的工具。旧引擎的 `tool_filter` 同样放行 `user_data_` 前缀，因此不是本次迁移引入的回归；修法应在 MCP 服务端按登录身份加归属校验，记入阶段 4 遗留清单交用户决定。


## 已知遗留（用户判定为开发阶段可暂缓，本期不动）

硬编码 JWT 兜底密钥的"缺失即拒绝启动"、登录/注册限流、`API_HOST` 默认 `0.0.0.0`、alembic 声明但无 migrations、eslint 83 项 error、无 CI/pre-commit、前端 109 处 console.log、`requirements.txt` 里 `python-socks` 无用。
