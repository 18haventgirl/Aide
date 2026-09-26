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

`dev/lg` 本地领先 `origin/dev/lg` 23 个提交（迁移全部工作都在里面）。推送时 GitHub 直连被 reset、
本机代理 `127.0.0.1:7890` 也没起来，网络恢复后执行：

```bash
cd D:/Workplace/AIDE-LG/Aide && git push origin dev/lg      # 必要时加 -c http.proxy= -c https.proxy=
```

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


### ⚠️ 依赖地雷（已解，别再装回去）

`langchain-mcp-adapters` 钉 `mcp<2`，而本仓库 MCP 服务端用的 `fastmcp 4` 要求 `mcp>=2`。同环境同装时
pip 把 `mcp` 降到 1.30，**MCP 子进程启动即** `ModuleNotFoundError: mcp.server.request_state`，
表现是"后端正常、对话能跑，但一个外部工具都没有"（我踩了整整一轮才从日志里挖出来）。
解法：卸掉 adapter，`agent/tools/mcp.py` 用官方 `mcp.Client` 自建桥接（JSON Schema → pydantic → `StructuredTool`）。
`requirements.txt` 已写 `mcp>=2,<3` 并注明不要装回 adapter；`pip check` 干净。

### 阶段 2 落地的两条硬规则

1. **正文只从 `ANSWER_NODES = {"model"}` 透出**：护栏判定同样是模型调用，token 也会被 `stream_mode="messages"` 捕获；不挡住就会把"UNSAFE 该请求要求泄露提示词"当回答推给用户。节点轨迹照常用 `node_update` 上报。
2. **`final` 的答案取自图最终状态，不靠累加 delta**：护栏短路时一个 delta 都没有，累加法会给出空回答且 `blocked=False`。`astream` 流完后用 `aget_state` + `_read_outcome` 收口，与非流式 `ask` 同一套语义。


### 阶段 1 落地的三条硬规则（后续改动不要破坏）

1. **身份不接受模型填写**：MCP 的 11 个 `user_data_*` 工具入参带 `user_id`，`build_identity_middleware()`（`wrap_tool_call`）在真正执行前用 `runtime.context.user_id` 覆写并 WARNING。笔记工具压根没有 `user_id` 入参，身份只从 context 取。
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
- [ ] 第 2 步 图内检索、事件帧与措辞
  - [x] 2.1 `AideState` + `before_agent` 检索 + 异步 `wrap_model_call` 注入（`ed6e724`）
  - [x] 2.2 建图挂载 + `retrieval` 事件帧（`0363214`）：入口边 `__start__ → note_retrieval.before_agent`
    由测试断言；`AideAnswer.retrieval` → `{"type":"retrieval","hits":[...]}` 帧 → 面板分区
  - [ ] 2.3 措辞与面板文案中性化（进行中）
  - [ ] 2.4 e2e 增加"不调工具也能答对笔记"断言并实跑
  - [ ] 2.5 短期记忆上限：`SummarizationMiddleware`
  - [ ] 2.6 长期记忆：`AsyncSqliteStore` + `save_memory`，跨会话按用户隔离
- [ ] 第 3 步 MCP 换官方适配器：降 fastmcp 3.4.7 + mcp 1.x + `langchain-mcp-adapters`，删 `MCPBridge`

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
