# LangGraph 迁移设计（Aide → LG-Aide）

- 分支：`dev/lg`　基线锚点：`306312d`（`origin/dev/lg`，用户已验收"完美"）
- 日期：2026-09-26　状态：已获用户批准，进入实现计划阶段
- 目标：把编排引擎从 OpenAI Agents SDK 换成 LangGraph，使本分支的卖点变成 **LangGraph + 自研 RAG**

## 1. 已确认的决策（用户选择）

| 议题 | 决策 |
| --- | --- |
| 迁移方式 | 一步硬切：删除 `openai-agents`，不做双引擎并存；回退靠 git 锚点 `306312d` |
| agent 拓扑 | 收敛为**单 agent + 工具图**，不再做 Triage/handoff 多代理 |
| 会话状态 | 引入 `AsyncSqliteSaver` checkpointer，与 MySQL 会话表并存 |
| RAG | **先验证自研 RAG**（召回正确性），再接进图 |
| 事件契约 | 前端右侧面板改为**图执行轨迹 + 工具清单**；其余 WS 事件语义尽量沿用 |
| 模型接入 | `langchain-openai` 的 `ChatOpenAI(base_url=DeepSeek)` 直连 |
| 验收力度 | 端到端脚本验证 + pytest 集成测试（可重复回归） |

## 2. 现状勘察证据

**SDK 耦合面**（全后端仅 4 个文件）：

| 文件 | 说明 |
| --- | --- |
| `agent/personal_assistant_manager.py` | 32 处：6 个 Agent、handoffs、MCPServerStreamableHttp、tool_filter、LitellmModel |
| `api/websocket_api.py` | 16 处：`Runner.run_streamed` + 流事件消费 |
| `agent/guardrails.py` | 2 处：`Agent`/`Runner`/`InputGuardrail` |
| `tests/test_guardrails.py` | 3 处 |

被替换的 SDK 能力仅 5 类：`Agent`+`handoffs`、`Runner.run_streamed` 流事件、`MCPServerStreamableHttp`+`tool_filter`、`LitellmModel`、输入护栏。业务层（MySQL/Chroma/笔记/待办/认证/MCP 服务端）与框架无关，**不改动**。

**LangGraph 生态实测版本**（PyPI 查询，2026-09-26）：

```
langgraph                    1.2.12
langchain                    1.4.2
langchain-core               1.6.5
langchain-openai             1.6.6
langchain-mcp-adapters       0.3.2
langgraph-checkpoint-sqlite  3.1.1
```

**在一次性环境（conda `lg-langgraph-spike`，与项目环境隔离，用完删除）实测到的 API**：

```python
langchain.agents.create_agent(model, tools, system_prompt, middleware,
    response_format, state_schema, context_schema, checkpointer, store,
    interrupt_before, interrupt_after, debug, name, cache)

AgentMiddleware 钩子: before_agent / before_model / after_model / after_agent /
  wrap_model_call / wrap_tool_call（均有 a* 异步版本）+ name / state_schema

内置 middleware: SummarizationMiddleware, ToolErrorMiddleware, ToolRetryMiddleware,
  ModelCallLimitMiddleware, ModelFallbackMiddleware, PIIMiddleware,
  HumanInTheLoopMiddleware, TodoListMiddleware, LLMToolSelectorMiddleware, ...

langchain_mcp_adapters.client.MultiServerMCPClient(
    connections: {name: StreamableHttpConnection|SSE|Stdio|Websocket},
    tool_interceptors, tool_name_prefix: bool = False, handle_tool_errors: bool = True)
  方法: get_tools() / get_prompt / get_resources / get_server_info / session

langgraph.checkpoint.sqlite.SqliteSaver / .aio.AsyncSqliteSaver   # 可用
langgraph.graph.StateGraph, MessagesState, START, END             # 可用
langchain.tools.tool                                              # 可用
```

`create_react_agent`（langgraph.prebuilt）已被标记废弃，官方路径是 `create_agent`。

## 3. 架构与目录

```
backend/agent/
  runtime.py      # 唯一对外入口。持有编译后的图 + 用户上下文缓存；把 LangGraph 流事件翻译成 WS 事件
  graph.py        # 建图：create_agent(model, tools, middleware, checkpointer, context_schema, name="Aide")
  context.py      # UserContext(user_id, lat, lng, preferences 快照) —— 取代 PersonalAssistantContext
  middleware.py   # SafetyMiddleware + RelevanceGuardrail（before_model 钩子）
  tools/
    notes.py      # 自研 RAG 工具：search_my_notes / save_note / update_note_status
  history.py      # MySQL 业务历史写入器（新文件，取代 agent_session.py 的职责）
```

- 删除：`agent/personal_assistant_manager.py`、`agent/guardrails.py`（协议解析函数 `_parse_verdict`/`_to_text` **迁到** `agent/middleware.py` 复用，现有针对它们的测试随之改 import，不降低覆盖）、`agent/agent_session.py`（阶段 4 删，其"写 MySQL 历史 + 缓存会话状态"的职责由 `history.py` 与 checkpointer 接管）。
- 依赖：新增上表 6 个包；删除 `openai-agents`、`openai-agents[litellm]`、`litellm`。
- **MCP 工具继续复用现成的 8102 服务端**（29 个工具不重写），接入方式换成 `MultiServerMCPClient(..., tool_name_prefix=True)`，其产出的 `weather_get_current_weather` 等前缀名与现有 `tool_filter` 结果一致，因此 `mcp-serve/` 侧零改动。

**模型名语义变化（重要）**：litellm 需要 provider 前缀（`openai/deepseek-chat`），LangChain 走 openai SDK 只要模型本名（`deepseek-chat`）。`env.example` 与 `.env` 改为 `OPENAI_CHAT_MODEL=deepseek-chat`，并在读配置处做一次去前缀兼容（`openai/xxx → xxx`），避免旧 .env 直接崩。

## 4. 数据流与 WS 事件契约

```
浏览器 ──WS chat──▶ api/websocket_api.py ──▶ runtime.ask(user_id, conversation_id, text)
                                              config = {"configurable": {"thread_id": conversation_id}}
                                              context = UserContext(...)
                                                 ▼
                                    graph.astream(stream_mode=["messages","updates"])
   ├─ AIMessageChunk          ─▶ AI_RESPONSE {type:"stream", delta}         （沿用现有流式协议）
   ├─ updates: model 节点      ─▶ AI_RESPONSE {type:"message", agent:"Aide"}
   ├─ updates: tools 节点      ─▶ {type:"tool_call"} / {type:"tool_output"}  （沿用现有）
   ├─ 节点进入/退出            ─▶ {type:"node_update", node, status}          （新增）
   ├─ 首轮启动时               ─▶ {type:"tools_list", tools:[...]}            （新增，喂前端工具清单）
   └─ state["guardrail_checks"] ─▶ completion.guardrails                     （沿用现有字段与前端面板）
```

- 前端只改 `AgentPanel`：原"代理列表"卡片 → "图执行轨迹"（`node_update`）+"可用工具"（`tools_list`）。消息流、事件流、护栏面板、上下文面板不动。
- 旧 `handoff` 事件不再产生；前端对该 type 的渲染分支保留（无害），不做破坏性删除。

**权威边界**：checkpoint 是**对话状态的唯一真相**（模型记忆、恢复、时间旅行都来自它）。MySQL 的 `conversations`/`chat_messages` 降级为**展示与检索副本**：每轮结束由 `history.py` 追加写，不再回灌给模型作为记忆输入（避免两套历史互相污染）。会话表结构不变。

## 5. RAG：先验证，再接入

阶段 A（验证，不接图）：新增离线可跑的召回测试 `backend/tests/test_rag_recall.py`：
- 用固定种子写入 ~15 条中文笔记到临时 Chroma 目录（`CHROMA_PERSIST_DIR` 指向 tmp_path）
- 对 8 组「查询 → 应命中标题」断言 top-3 命中；含 2 组**零词面重叠**的纯语义查询
- 断言更新后检索跟随新内容、删除后不再命中
- 不依赖 MySQL、不依赖 LLM 网络（embedding 走本地 bge；测试环境需已下载模型，缺失时 `skip` 并给出明确提示）

阶段 B（接入）：做成工具而非图前置节点 —— `search_my_notes(query, top_k=5)`、`save_note(title, content, tag)`，由模型自主决定何时检索。理由：与 MCP 工具同构、保持单 agent 拓扑、避免每轮强制检索的开销。前置 retrieval 节点作为后续可选项，不进本期范围。

## 6. 护栏在 LangGraph 里的等价实现

- 两道检查放在 `before_model` 钩子里（图执行前、模型调用前），判定用**同一个模型的第二条链**、纯文本结论协议（沿用现有"第一行关键词 + 第二行理由"，DeepSeek 不支持 `response_format=json_schema`，structured outputs 会整条打回）。
- 命中 → 不进入模型：写一条固定中文拒答 + `guardrail_checks` 记录，直接走到 END，`is_error=False`（保持"拦截不是故障"的既有语义）。
- 判定自身异常 → 放行并记录 `护栏判定不可用，已放行: …`，保持现语义。
- `guardrail_checks` 存在 graph state（`PrivateStateAttr` 风格，不下发给模型），由 `runtime.py` 取出塞进 `completion.guardrails`。

## 7. 错误处理与可观测

| 故障 | 行为 |
| --- | --- |
| 工具抛异常 | `ToolErrorMiddleware` 转成工具错误消息给模型，整轮不崩 |
| 模型不可用/鉴权失败 | 与现状一致：`completion.is_error=True` + 错误文案；WS 不挂死（现有超时与并发发送队列保留） |
| MCP 服务不可用 | 图仍可构建运行，工具集为空并 WARNING（对话退化为纯聊天）；不阻断启动 |
| checkpoint 文件损坏/线程不存在 | 视为新线程，记 WARNING，不抛给前端 |
| 递归上限 | `config={"recursion_limit": 25}`，防工具死循环 |

日志一律走 `logging`，不新增 print（现存 print 不在本期清理范围）。不接 LangSmith（离线优先）。

## 8. 测试与验收

**pytest 集成（离线、不依赖 LLM 网络）**：
1. `test_graph_build.py`：用假模型（`langchain_core.language_models.fake_chat_models`）构图成功；工具集非空、middleware 顺序正确
2. `test_guardrail_middleware.py`：放行/拦截/判定异常三分支的状态与记录断言（含协议解析，沿用现 `_parse_verdict` 测试）
3. `test_rag_recall.py`：第 5 节阶段 A
4. `test_runtime_events.py`：把 astream 产出喂给翻译层，断言 WS 事件序列与字段（`stream/message/tool_call/tool_output/node_update/completion`）
5. `test_checkpoint_roundtrip.py`：同一 `thread_id` 两轮对话后 state 含历史；重启（新建 saver 实例）后仍可恢复
6. 保持现有 27 项全绿

**端到端脚本（真实 DeepSeek）**：多轮记忆、工具调用（天气 + 个人数据）、护栏拦截、重启后 checkpoint 恢复、笔记语义检索、前端页面人工复测清单。

**通过标准**：三件套（8100/8102/5199）+ MySQL 起来后，脚本全绿、pytest 全绿、浏览器可注册登录并完成一次带工具调用的对话。

## 9. 实施阶段（每阶段结束都跑回归并提交）

1. **阶段 0 · 验证 RAG**（第 5 节阶段 A）——不动业务代码，先把自研 RAG 的召回钉住
2. **阶段 1 · 引擎骨架**：`context.py`/`graph.py`/`middleware.py`/`tools/notes.py` + 依赖增删；`runtime.py` 先做非流式 `ask()`
3. **阶段 2 · 流式与事件**：接 `astream`，翻译层与 WS 协议，checkpoint 落 SQLite
4. **阶段 3 · 前端面板**：`node_update`/`tools_list` + 图执行轨迹与工具清单
5. **阶段 4 · 收尾**：删除旧引擎文件、README/env.example 更新、端到端与回归全跑、`docs/PROGRESS.md` 汇总

## 10. 风险与待实测项（诚实清单，实现中逐条勾掉）

- `create_agent` 的 `context_schema` 如何把 `UserContext` 注入到工具（工具签名要拿 `runtime`/`ToolRuntime`）：**未实测**，阶段 1 第一件事就是 spike 验证；不通则退化为"工具参数显式传 user_id + 服务端强制覆写"。
- `stream_mode=["messages","updates"]` 同时开启时的产出形状（tuple 解包方式）：**未实测**，阶段 2 spike。
- `AsyncSqliteSaver` 在 uvicorn 多并发连接下的文件锁行为：**未实测**；必要时按用户分库文件或改进程内串行队列。
- `tool_name_prefix=True` 与现有 29 个工具名是否完全一致（尤其 `user_data_*`）：阶段 1 实测比对。
- 单 agent 挂 29+ 工具的 token 成本与选择准确率：DeepSeek 上下文够用，但要实测一轮"天气+笔记"复合任务的工具命中；不理想则用 `LLMToolSelectorMiddleware` 或按域裁剪。
- 会话标题生成（原 `Conversation Title Agent`）在单 agent 拓扑下的去处：改为每轮后一次独立小调用，不进图（YAGNI）。
- MySQL 会话表与 checkpoint 的 thread_id 对齐（沿用现有 `conversation_id` 字符串）。

## 11. 本期不做

多 agent supervisor 图、图前置 RAG 节点、LangSmith/可观测平台、pgvector 迁移、历史数据迁移脚本、print 全量清理、eslint 83 项治理、限流与密钥硬失败（用户判定为开发阶段可暂缓）。
