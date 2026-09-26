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

## 待办：推送

已推送完成（2026-09-26）：`306312d..dfbfc33 dev/lg -> dev/lg`，43 个提交上了 origin。
后续改动照常 commit + push 工作分支即可，不走 PR。

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
- [x] 阶段 2（前 3 项）：SQLite checkpoint + `translate_stream` 流式翻译 + WebSocket 切新引擎
  - 提交：`096ee4a` checkpointer → `443f54a` 相关性护栏校准 → `87fe53b` 流式翻译层 → `a8c06a1` MCP 桥接与版本冲突 → `ece9139` WebSocket 切 LangGraph
  - 全量 `pytest tests -q`：**108 passed**，全部离线可跑
  - 真实 WS 端到端（注册→连接→三轮对话）：`tool_count=31`（2 个笔记工具 + 29 个 MCP）、过程帧 `tools_list/node_update/delta`、TURN2 靠 checkpoint 答出"你叫小林，在广州做安卓开发"、TURN3 真调 `weather_get_daily_weather_forecast`
  - 探针脚本 `backend/_ws_probe.py`（临时，阶段 4 会固化成 `scripts/e2e_langgraph_check.py`，不提交）
- [x] 阶段 3：前端图执行轨迹与工具清单（`8cfe711` 过程帧接入 + `5c87241` 面板组件）
  - 浏览器实测（5199，账号 lguser）：流式逐字正常；同一会话第二轮"你叫小陈，在杭州工作"由 checkpoint 记忆答出；
    轨迹显示 安全护栏/相关性护栏/模型推理/工具执行（中文标签 + 原始节点名）；工具清单 31 个按来源分组；
    护栏分区显示两条检查与理由；顺手修了时间戳（后端给 epoch 秒，前端 `new Date(秒)` → 显示在 1970 附近）
- [x] 阶段 4：删除旧引擎、文档、全量回归（迁移完成）
  - [x] 4.1 删旧引擎：删 `agent/personal_assistant_manager.py`、`agent/guardrails.py`、`tests/test_guardrails.py`
    （12 项旧护栏用例，覆盖面已由 `test_guardrail_middleware.py` 取代）；`core/performance_manager.py`
    从 319 行瘦到 103 行，只管会话管理器缓存；`requirements.txt` 去掉 `openai-agents` / `openai-agents[litellm]`；
    README 新增"编排架构"一节与 `CHECKPOINT_DB` / 模型名说明。
    **验证方式**：把 `openai-agents` 与 `litellm` 从环境里真卸掉后 `pytest tests`（100 passed）与
    `python -c "import main"` 均通过，`pip check` 干净 —— 说明没有隐性残留依赖。
  - 与计划的两处偏差（都有实测理由）：
    1. 计划要删 `agent/agent_session.py` —— **不删**：它只依赖 `ChatMessageService`/`ConversationService`，
       与 SDK 无关，且 MySQL 展示副本正是它在写（实测会话 26 有 3 human + 3 ai）；删掉等于砍掉副本写入。
    2. 计划要让 `performance_manager` 持有 `AideRuntime` —— **不做**：`agent.runtime.aide_runtime` 已是模块级
       单例并被直接引用，再包一层只是第二个引用点，属于无收益的间接层。
  - [x] 4.2 端到端会话验收：`backend/scripts/e2e_langgraph_check.py`（17 项断言 + 退出码，可重复跑）
    实跑结论 **全部通过**（真实 DeepSeek + 本地 MCP + 本地向量库，旧 SDK 已从环境卸载后重启的服务）：
    注册/`/auth/me`/健康检查 → 过程帧工具清单 31 个 → 首帧带回 `conversation_id` → 115 个 delta 逐字 →
    `weather_get_daily_weather_forecast` 真调用 → 轨迹含护栏/模型/工具节点 → `user_data_create_todo` 写待办 →
    多轮记忆答出"下班买牛奶" → 提示词注入被安全护栏拦下且未套出提示词 → RAG 零词面查询"植物养护提醒"
    命中"阳台绿萝浇水" → 代理自己用 `search_my_notes` 答出"两周一次" → 该 thread_id 已在 SQLite 检查点文件里。
    验收中修掉的一处脚本口径：注入那句被安全护栏 `jump_to end` 后相关性护栏不再运行，"必须两条记录"的断言是错的，
    正确口径是"有记录且 failed 与 blocked 一致"。
  - 最终回归：`pytest backend/tests -q` → **100 passed**（旧的 12 项 SDK 护栏用例随文件删除，覆盖面在
    `test_guardrail_middleware.py`）；`python -c "import main"` 通过；`pip check` 干净。


### ⚠️ 依赖地雷（已解，改 MCP 依赖前先看这段）

`langchain-mcp-adapters` 钉 `mcp<2`，而 `fastmcp 4` 要求 `mcp>=2` —— **这两者不能共存**。
同环境同装时 pip 会把 `mcp` 降到 1.30，而 fastmcp 4 的代码用到 mcp 2.x 才有的符号，
表现为"MCP 子进程启动即 `ModuleNotFoundError: mcp.server.request_state`"，
看上去"后端正常、对话能跑"，实际一个外部工具都没有（我踩了整整一轮才从日志里挖出来）。

当时为了保住 fastmcp 4 而手写过一版桥接；**后来证实那是绕远路**：真正的解法是把服务端降到
`fastmcp 3.4.7`，与 `mcp 1.30` + `langchain-mcp-adapters 0.3.2` 组成实测通过的三角，
手写桥接已删除（见第 3 步）。所以现在这套约束是：

```
fastmcp>=3.4.7,<4      # 服务端：mount(namespace=...) 在 3.x 与 4.x 都可用，2.x 没有
mcp>=1.24,<2           # adapters 的上限；fastmcp 3.4.7 也接受
langchain-mcp-adapters>=0.3,<1
```

要动其中任何一个，先 `pip check`，再单独起 8102 数一遍工具数（应为 29，名字带
`weather_/news_/recipe_/user_data_` 前缀）。**不要**只升 `fastmcp` 到 4：那会重新撞上开头那个死结。

### 阶段 2 落地的两条硬规则

1. **正文只从 `ANSWER_NODES = {"model"}` 透出**：护栏判定同样是模型调用，token 也会被 `stream_mode="messages"` 捕获；不挡住就会把"UNSAFE 该请求要求泄露提示词"当回答推给用户。节点轨迹照常用 `node_update` 上报。
2. **`final` 的答案取自图最终状态，不靠累加 delta**：护栏短路时一个 delta 都没有，累加法会给出空回答且 `blocked=False`。`astream` 流完后用 `aget_state` + `_read_outcome` 收口，与非流式 `ask` 同一套语义。


### 阶段 1 落地的三条硬规则（后续改动不要破坏）

1. **身份不接受模型填写**：MCP 那批 `user_data_*` 工具（实测 17 个）入参带 `user_id`，`build_identity_middleware()`（`wrap_tool_call`）在真正执行前用 `runtime.context.user_id` 覆写并 WARNING。笔记工具压根没有 `user_id` 入参，身份只从 context 取。换成官方适配器后这条仍然生效（e2e 日志可见 `收到 user_id=1，已按登录身份覆写为 28`）。
2. **护栏每轮只判一次**：`before_model` 在工具回环里会再次触发，`_resuming_after_tool()` 检测最后一条是 `ToolMessage` 时直接返回 `None`。否则同句话判两遍：多两次 LLM 往返、面板重复行，且第二遍会把模型自己的回答当成判定结论。
3. **工具异常必须变成字符串**：`search_my_notes`/`save_note` 对"服务不可用/无上下文/无命中/向量库挂了"都返回中文句子，其中向量检索失败会回退关键词检索；`load_mcp_tools()` 连不上返回 `[]`，对话继续只是没外部工具。


## 当前任务：底层复用重构（用标准件替换我手写的部分）

起因：用户读源码发现 `backend/agent/*.py` 里几乎没引用 LangGraph/LangChain 标准件——检索层与
MCP 装载都是我手写的。本轮目标=能复用库的地方换成库，并把宣传式措辞改成工程描述。
设计 `docs/superpowers/specs/2026-09-26-langgraph-reuse-design.md`，计划
`docs/superpowers/plans/2026-09-26-langgraph-reuse.md`（13 个任务）。

### 进度

- [x] 第 1 步 检索层换标准件（`8d8f1a4` … `ed6e724`，共 6 次提交）
  - 新增 `core/retrieval/{config,embeddings,store,documents}.py`：`HuggingFaceEmbeddings`（本地 bge，
    `normalize_embeddings=True`）+ `langchain_chroma.Chroma`（每用户一个集合，显式 `hnsw:space=cosine`）
  - 删除 `core/vector_core/`（自写 Chroma 封装）；`service_manager`、`/api/health`、MCP 服务端探针
    同步改走 `vector_health()`
  - `note_service` 的创建/更新/删除/检索四条路径改走标准件；`scripts/reindex_notes.py` 幂等重建，
    实跑两次总量一致：**11 个用户 / 17 篇笔记**
  - 召回闸门 `tests/test_rag_recall.py`：沿用同一份 5 文档语料 + 8 组零词面查询，断言与换件前一致，实跑绿
  - 实测数字：零词面查询「植物养护提醒」→「绿萝浇水」相关度 **0.54**
- [x] 第 2 步 图内检索、事件帧与措辞（`ed6e724` `0363214` `592e174` `275b926` `0280079` `5eb2094`）
  - [x] 2.1 `AideState` + `before_agent` 检索 + 异步 `wrap_model_call` 注入（`ed6e724`）
  - [x] 2.2 建图挂载 + `retrieval` 事件帧（`0363214`）：入口边 `__start__ → note_retrieval.before_agent`
    由测试断言；`AideAnswer.retrieval` → `{"type":"retrieval","hits":[...]}` 帧 → 面板分区
  - [x] 2.3 措辞与面板文案中性化（`592e174`）：删掉 `NODE_LABELS`/`nodeLabel` 的中文美化映射，
    节点行直接显示真实节点名；分区标题改为 执行节点/笔记检索命中/工具/护栏/上下文/运行输出；
    `AGENT_DESCRIPTION`、工具说明、README 里的"自研 RAG"全部换成中性技术名
  - [x] 2.4 e2e 实跑：**20 项全通过，退出码 0**（真实 DeepSeek + 本地 Chroma + 8102 MCP）
    - 检索节点确实排在最前：`nodes=['note_retrieval.before_agent', 'Safety Guardrail.before_model',
      'Relevance Guardrail.before_model', 'model', 'tools']`
    - 前置检索命中 `('阳台绿萝浇水', 0.67)`，模型**一次工具都没调**（`calls=[]`）就答出
      "土表发白就浇透，冬天两周一次"，并按系统提示词注明了来源是笔记
    - 因此把原来那条"必须调 `search_my_notes`"的断言改成"能答对自己笔记里的内容"：架构变了，
      旧断言考的是已经不必要的路径；工具路径仍由 `tests/test_agent_retrieval.py` 等覆盖，
      这一轮实际走了哪条路打在 detail 里给人看
    - 面板实测（5199，浏览器结构快照）：分区标题与表头副标题已是中性名，空态文案正常。
      节点行与命中行的**填充态没做视觉确认**（in-app 浏览器拿不到可视视口，截屏不可用），
      只有协议单测 + e2e 帧捕获覆盖，需要人眼确认时再开浏览器看一次
  - [x] 2.5 短期记忆上限：`SummarizationMiddleware`（`0280079`）
    - 节点位置实测：`note_retrieval.before_agent → SummarizationMiddleware.before_model →
      Safety/Relevance Guardrail.before_model → model`，也就是压缩发生在护栏与业务模型之前
    - 阈值 `SUMMARIZE_TRIGGER_TOKENS=6000` / `SUMMARIZE_KEEP_MESSAGES=8`，都可用环境变量覆盖
    - **压缩真的会发生**（`test_summarization_replaces_early_history`）：把阈值调到最低、喂 13 条
      历史后，状态里只剩 1 条带 `lc_source=summarization` 的摘要消息，最早那条提问已不在，
      本轮作答仍是最后一条。默认阈值下的长会话（>6000 token）仍未跑过，但触发逻辑已被锁住
  - [x] 2.6 长期记忆：`agent/memory.py`（AsyncSqliteStore + 语义索引，复用本地 bge）
    - 写入只由 `save_memory` 工具决定（`agent/tools/memory.py`，身份与 store 都取自 runtime）；
      召回走 `before_agent` + `wrap_model_call` 临时注入，和笔记检索同一个模式
    - 单测 6 项：命名空间隔离（user 3 看不到 user 9 的条目）、注入但不落历史、无 store 时降级
    - **实跑中发现并修掉一个真 bug**：新会话第一句"我是做什么工作的"被相关性护栏判为跑题拦下——
      判词只看到孤零一句话，不知道助手本来就该记得用户的事实。修法是把范围写清
      （`agent/middleware.py`：跨会话的个人信息询问属正常范围），不是删护栏
    - e2e 补两项后 **22 项全通过，退出码 0**：`save_memory` 被调用 → 换一个 conversation_id
      再问 → 答"安卓开发。"，且 `calls=[]`、新线程无任何历史可依赖
    - 存储文件 `backend/data/lg-aide-memory.sqlite`（`MEMORY_DB` 可覆盖，`data/` 已在 .gitignore）
- [x] 第 3 步 MCP 换官方适配器（`812513a` 依赖 → `1371740` 装载）
  - 降级实测：`fastmcp 3.4.7 + fastmcp-slim 3.4.7 + mcp 1.30.0 + langchain-mcp-adapters 0.3.2`，
    `pip check` → **No broken requirements found**（回退锚点：升级前是 fastmcp 4.0.9 + mcp 2.2.0）
  - 服务端冒烟：8102 在 fastmcp 3.4.7 下启动正常，`MultiServerMCPClient(tool_name_prefix=False)`
    取到 **29 个工具，名字与降级前逐一位一致**（对照基线 `mcp_baseline.json` 比对 same: True）
  - 删掉自写桥接：`agent/tools/mcp.py` 从 155 行（JSON Schema→pydantic→StructuredTool 手写）
    缩到 36 行；`MCPBridge`、`args_model_from_schema`、`tests/test_mcp_bridge.py` 一并删除；
    runtime 不再持有 MCP 连接（适配器每次调用自开会话），`self._bridge` 全清
  - 新增 `tests/test_mcp_tools.py` 5 项：装载结果、连不上降级成 `[]`、`tool_name_prefix=False`、
    URL 只从 `RuntimeConfig` 来、可覆盖
  - **身份覆写没因换适配器失效**（实测日志）：
    `WARNING:agent.middleware:工具 user_data_get_user_notes 收到 user_id=1，已按登录身份覆写为 28`
    `WARNING:agent.middleware:工具 user_data_create_todo 收到 user_id=1，已按登录身份覆写为 28`
- [x] 收尾：离线全量 **145 passed**；端到端 **23 项全通过、退出码 0**（连跑两轮稳定）

### 收尾时顺手修掉的两个真问题（都是实跑撞出来的）

1. **`/api/health` 空闲时误报 degraded**：最后一个 WS 连接断开时心跳任务会被取消，
   旧逻辑据此判 `websocket: not_running` → 整体 degraded。表现为"没人聊天的时候服务看起来是坏的"，
   而且 e2e 是否通过取决于当时有没有别的客户端连着（浏览器标签开着就过，关掉就挂）。
   改成：有连接却没心跳才算故障，空闲算健康。`tests/test_system_health.py` 4 项锁住这个语义。
2. **相关性护栏拦住跨记忆提问**（见 2.6）：新会话第一句"我是做什么工作的"被拦，
   因为判词只看到孤零一句话。修法是把范围写清，不是删护栏。

### 验收清单逐条对账（计划文件末尾那 8 条）

| # | 条目 | 状态 | 证据 |
| --- | --- | --- | --- |
| 1 | 离线全量绿，且召回断言与迁移前一致 | 实测 | `145 passed`；`tests/test_rag_recall.py` 8 组零词面查询断言逐条未改 |
| 2 | `pip check` 干净，requirements 写明约束组合 | 实测 | `No broken requirements found`；约束块写在 `requirements.txt` 开头 |
| 3 | 不再有自写 Chroma 封装与自写 MCP schema 桥接 | 实测 | `core/vector_core` 源码与残留 `__pycache__` 均已删除；`MCPBridge`/`args_model_from_schema` 全仓库零引用 |
| 4 | 编译出的图里有 `note_retrieval.before_agent` 且排在最前 | 实测 | 单测断言入口边；e2e 轨迹 `nodes[0]='note_retrieval.before_agent'` |
| 5 | 端到端全通过，含"不调工具也能答对笔记" | 实测 | 23 项全 PASS、退出码 0，`calls=[]` 且答案含"两周一次" |
| 6 | UI 与文档无宣传式措辞，节点显示真实名字 | 实测 | 全仓库 `自研/卖点` 零命中；浏览器实测节点行显示 `note_retrieval.before_agent` 等原始名 |
| 7 | 短期记忆有界 | 实测 | 阈值调到最低跑 13 条历史：状态里只剩 **1 条** `lc_source=summarization` 的摘要，最早的提问已不在，本轮作答仍是最后一条（`test_summarization_replaces_early_history`） |
| 8 | 长期记忆跨会话生效且按用户隔离 | 实测 | e2e 换新 conversation_id 答出"安卓开发"；单测断言 user 3 看不到 user 9 的条目 |

### 本轮重构的提交（`306312d` 之后，均已推送）

```
e93f7ec feat: 检索层引入 langchain-chroma 与 langchain-huggingface，统一 Embeddings 来源
ecd2040 refactor: 笔记服务的向量写入/更新/删除/检索改走 langchain-chroma
a5e4df9 refactor: 删除自写 Chroma 封装，检索层统一到 langchain-chroma
800ea55 fix: 检索层自己加载 .env 并对缺失的本地模型目录快速失败（离线不再挂起联网重试）
949f610 feat: 笔记向量索引重建脚本（幂等，实测两次均 11 用户 17 条）
ed6e724 feat: 图状态与笔记检索前置钩子（before_agent 检索 + 异步 wrap_model_call 注入）
58d2827 docs: 记忆架构选型（短期压缩 + 长期 Store）与设计依据
0363214 feat: 检索节点接入建图并透出 retrieval 事件帧
592e174 refactor: 措辞与面板文案改为中性技术名，显示真实节点名
275b926 test: e2e 增加前置检索断言（检索帧与不依赖工具的召回）
0280079 feat: 接入 SummarizationMiddleware 给短期记忆设上限
5eb2094 feat: 长期记忆（Store + save_memory，跨会话按用户隔离）
812513a chore: MCP 依赖降到 fastmcp 3.4.7 + mcp 1.x 以启用官方适配器
1371740 refactor: MCP 工具装载改用 langchain-mcp-adapters，删除自写桥接
dfbfc33 docs: 检索层与 MCP 重构收口（含健康检查空闲态修复）
```

（`fa0b642` 是给旧向量层适配 chromadb 1.3+ 协议的过渡提交，随 `core/vector_core` 一起删除了。）

### 待办（本轮没做，别当成已完成）

- `docker-compose.yml` 里那个 8101 的 Chroma 服务已经没人连了（检索统一走进程内持久化），
  要么删掉要么在注释里说明保留原因——留给用户定。
- 面板上"长期记忆注入了什么"目前没有分区显示（只走日志），需要的话按 `retrieval` 帧同一套加。
- 默认阈值（6000 token）下的真实长会话仍未跑过；触发逻辑由单测把阈值调到最低来证明。

### 本轮新增的硬规则（后续改动不要破坏）

1. **检索命中不进 `messages`**：只写 `AideState.retrieved`，给模型看靠 `wrap_model_call` 临时插入的
   SystemMessage。写进 messages 会被 checkpoint 永久保留，多轮后历史堆满检索片段。
2. **`tests/conftest.py::fake_retrieval_backend` 是 autouse**：任何跑图的单测都不会加载本地 bge，
   也不会往真实 Chroma 目录写。要真向量的测试自己再 patch 同一批函数（后申请者生效）。
3. **本地 embedding 只允许指向工作区目录**：`core/retrieval/embeddings.py` 对不存在的本地目录直接抛错，
   只有 `org/name` 形式的 hub 模型名才放行联网（离线时曾挂 5 次网络重试）。

## 待验证（不许当作事实使用）

1. ~~`create_agent` 的 `context_schema` 如何把 `UserContext` 注入工具~~ **已实测（阶段 1）**：工具签名写 `runtime: ToolRuntime[UserContext] = None` 即可，`langchain.tools` 有再导出（实际定义在 `langgraph.prebuilt.tool_node`）；该参数会被自动排除在 `tool_call_schema` 之外，模型看不到也填不了。单独 `tool.ainvoke({...})` 时 `runtime` 为 `None`，显式传 `runtime=None` 反而被 pydantic 拒（类型是 dataclass），要省略键。
2. ~~`stream_mode=["messages","updates"]` 同时开启时的产出形状~~ **已实测（阶段 2）**：产出 `(mode, payload)`；`messages` 的 payload 是 `(chunk, meta)`，meta 里有 `langgraph_node`。**关键坑：护栏判定也是模型调用，它的 token 同样会进这条流**，必须按节点白名单只透出 `model`，否则内部判词会当回答推给用户。
3. `AsyncSqliteSaver` 在 uvicorn 并发下的文件锁表现——**部分实测**：单连接多轮、跨连接同线程、进程重启后同线程均正常；多用户并发写同一库尚未压测（脚本 e2e 是单会话）。检查点文件必须长期持有上下文，建完图就退出 `async with` 会让下一轮撞在已关闭的连接上。
4. ~~`tool_name_prefix=True` 产出的工具名~~ **已实测（阶段 1）**：用 `tool_name_prefix=False`，29 个工具名原样为 `weather_/news_/recipe_/user_data_` 前缀，与 MCP 服务端一致；`load_mcp_tools()` 对运行中的 8102 真实返回 29 个。
5. 单 agent 挂 29+2 工具时 DeepSeek 的工具选择准确率与 token 成本——阶段 2 实测（首个冒烟选对了天气工具）
6. 会话标题生成改为每轮后一次独立小调用，效果是否够用——阶段 4
7. **新发现，待阶段 2 处理**：MCP 工具的 `ToolMessage.content` 不是纯文本，而是 `[{'type': 'text', 'text': '<json 字符串>'}]` 列表；直接 `str(m.content)` 会把 Python repr 灌给模型和面板，翻译层要取 `part["text"]` 再裁剪。
8. **新发现，遗留风险**：MCP 侧 `user_data_update_note / delete_note / update_todo / complete_todo / delete_todo` 只按 `note_id/todo_id` 定位记录，服务端不校验归属，所以"猜别人的 id 改别人的数据"这条路径仍然开着——身份覆写只挡得住带 `user_id` 入参的工具。旧引擎的 `tool_filter` 同样放行 `user_data_` 前缀，因此不是本次迁移引入的回归；修法应在 MCP 服务端按登录身份加归属校验，记入阶段 4 遗留清单交用户决定。


## 已知遗留（用户判定为开发阶段可暂缓，本期不动）

硬编码 JWT 兜底密钥的"缺失即拒绝启动"、登录/注册限流、`API_HOST` 默认 `0.0.0.0`、alembic 声明但无 migrations、eslint 83 项 error、无 CI/pre-commit、前端 109 处 console.log、`requirements.txt` 里 `python-socks` 无用。
