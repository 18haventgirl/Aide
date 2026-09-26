# LangGraph 与检索层重构设计（复用官方件）

日期：2026-09-26　分支：`dev/lg`　状态：待实现
前置文档：`2026-09-26-langgraph-migration-design.md`（SDK→LangGraph 迁移，已完成）

## 1. 触发原因

用户复核源码后指出三件事，均成立：

1. `backend/agent/` 下与框架相关的 import 只有 8 行，检索层与 MCP 装载层基本是自己实现的，
   看不出在用 LangGraph / LangChain 的抽象。
2. "自研 RAG" 这类表述过度包装。当前检索实现就是 Chroma + bge 向量 + top-k，功能普通，
   不该用卖点式措辞。
3. 前端面板文案偏宣传腔，要求简洁、工程级。

## 2. 决策依据（本地可复核，不是印象）

| 结论 | 证据 |
| --- | --- |
| `create_agent` 是库函数，且是官方推荐入口 | `langchain/agents/factory.py`；内部 `StateGraph(...)`、`add_node("model")`、`add_node("tools", ToolNode(...))`；`langgraph.prebuilt.create_react_agent` 带 `@deprecated(...请改用 create_agent)` |
| 生产级组装方式是 create_agent + middleware + 自定义 state | `deepagents/libs/deepagents/deepagents/graph.py:961`：`create_agent(model, middleware=..., context_schema=..., checkpointer=..., store=..., state_schema=DeepAgentState)` |
| 手写 StateGraph 的官方示例集中在 RAG 教学 notebook | `langgraph/examples/rag/*.ipynb`（agentic_rag / self_rag / crag / adaptive_rag） |
| 检索注入不需要重写循环 | `ModelRequest` 字段含 `messages/system_message/state/runtime`，且有 `override()`；`AgentMiddleware` 提供 `before_agent / before_model / wrap_model_call / wrap_tool_call / after_model / after_agent` |
| MCP 标准桥接可用，但要求服务端降级 | pip dry-run：`fastmcp>=2,<4` + `langchain-mcp-adapters>=0.3` + `mcp<2` + `langgraph>=1.2` 可一起解析（fastmcp 3.4.7 / mcp 1.30.0）；fastmcp 4.0.9 包内无任何 langchain 集成 |
| 降级不改服务端代码 | fastmcp 3.4.7 `server.py:2124 def mount(self, server, namespace=None, as_proxy=None, tool_names=None, prefix=None)`，与现用 `mount(x, namespace="...")` 同签名（`prefix` 已废弃） |
| RAG 标准件可安装 | 镜像有 `langchain-chroma 1.1.0`、`langchain-huggingface 1.2.2` |

## 3. 目标架构

```
                      ┌──────────────────────────────────────────────┐
浏览器 ──WS chat──▶ runtime.astream ──▶ create_agent(CompiledStateGraph)
                      │                    │
                      │  before_agent      │ retrieve_once：本轮检索一次
                      │    └─ 写 state.retrieved（不进 messages）
                      │  before_model      │ safety / relevance 护栏，命中 jump_to end
                      │  wrap_model_call   │ 把 retrieved 作为临时 SystemMessage 注入
                      │  wrap_tool_call    │ user_id 按登录身份覆写
                      │  model ⇄ ToolNode  │ 工具：检索/笔记/待办 + MCP 外部数据
                      │  checkpointer      │ AsyncSqliteSaver（对话真相）
                      └──────────────────────────────────────────────┘
                                          │
                                   MySQL 展示副本（会话/消息）
```

图的组装仍由 `create_agent` 完成；本项目只写节点级逻辑（钩子函数）与状态定义。

## 4. 依赖变更

```
+ langchain-chroma==1.1.0
+ langchain-huggingface==1.2.2
+ langchain-mcp-adapters            # 与 mcp<2 兼容的组合
~ fastmcp: 4.0.9 → >=3.4.7,<4
~ mcp:     2.2.0 → >=1.24,<2
```

变更后 `pip check` 必须干净；`requirements.txt` 注释同步改写，删掉"不要装 adapters"的旧告诫，
改为记录 fastmcp/mcp/adapters 三者必须一起满足的约束组合。

## 5. 检索层（替换手写向量封装）

### 5.1 组成

- `Embeddings`：`langchain_huggingface.HuggingFaceEmbeddings(model_name=LOCAL_EMBEDDING_MODEL,
  encode_kwargs={"normalize_embeddings": True})`，继续用 `backend/models/bge-small-zh-v1.5`。
- 向量库：`langchain_chroma.Chroma(collection_name=f"{CHROMA_COLLECTION_PREFIX}_user_{uid}",
  embedding_function=<上面的 Embeddings>, persist_directory=CHROMA_PERSIST_DIR)`。
  **保持现有的"每用户一个集合"布局**（实测：`lg_aide_user_1` 9 条、`lg_aide_user_3` 4 条），
  不改成单集合 + `where={"user_id":...}`：后者一旦某处漏传过滤条件就是跨用户读取，
  而按用户分集合把隔离交给命名空间本身。由一个按 uid 缓存 `Chroma` 实例的小工厂负责实例化
  （约 20 行，属于本项目职责，不是重造库能力）。
  统一走本地持久化模式；`CHROMA_CLIENT_MODE=http` 不再作为主路径，若显式设置则启动告警。
- 检索器：`vectorstore.as_retriever(search_kwargs={"k": DEFAULT_QUERY_LIMIT})`，
  用户隔离由集合名承担，不再叠加 metadata 过滤。
- 写入：笔记创建/更新/删除改走 `vectorstore.add_documents / update_documents / delete`。

### 5.2 必须处理的既有事实

1. **索引重建脚本（运维工具，不是迁移前提）**：本文初稿写的是"旧集合字段布局与
   `langchain-chroma` 不同，必须重算"，**该判断已被实测推翻**：现有集合本来就是
   `hnsw:space=cosine`、id 已是 `note_{id}`、文档已是"标题\n正文"、metadata 键也一致
   （实测 `lg_aide_user_1` 9 条可直接被新代码读出）。
   仍然交付 `backend/scripts/reindex_notes.py`，但定位是"换 embedding 模型或索引与
   数据库对不上时重算"，集合名保持不变（`{prefix}_user_{uid}`），幂等可重跑
   （实测跑两次都是 11 个用户 17 条）。
2. **召回质量门禁**：`tests/test_rag_recall.py` 现有 8 组查询断言（top-3 命中、更新后相关性反转、
   删除后不出索引）必须在新实现上原样通过；该测试是"没把检索改坏"的唯一判据，不允许改弱。
3. **REST 契约不变**：`POST /api/notes/{user_id}/search` 的响应结构保持
   `{success, data: {data: [{note_id,title,tag,score,text}], total}}`，前端零改动。
4. **`core/vector_core` 的去留**：被 `note_service`、`mcp-serve/user_data_tools.py`、`service_manager`
   引用。本次改为薄壳：只保留配置读取与 `Chroma` 实例工厂，删掉自写的 embedding 调用与相似度换算。

### 5.3 检索在图里的位置

- `retrieve` 作为 `before_agent` 钩子：每轮执行一次（工具回环不再重复检索），把
  `Document` 列表写入 `AideState.retrieved`。
- `wrap_model_call` 把 `retrieved` 渲染成临时 `SystemMessage`（`[笔记检索结果] …`）注入
  `request.messages`，**不写回 state**，因此不进 checkpoint、不污染多轮历史。
- 命中为空时不注入任何内容，也不编造；模型可继续正常回答或改用工具。不做自创的重试/改写查询逻辑。
- 参数：top-k 与相似度阈值沿用实测值（`SIMILARITY_THRESHOLD=0.35`、k=5）。
- 保留 `search_my_notes` 工具用于"换关键词再查"，但默认路径已有前置召回，不依赖模型主动调用。

## 6. MCP 层（删掉手写桥接）

- `agent/tools/mcp.py` 改为 `langchain_mcp_adapters.client.MultiServerMCPClient`，
  `tool_name_prefix=False`（服务端工具名已自带 `weather_/news_/recipe_/user_data_` 前缀，实测 29 个）。
- 删除自写的 JSON Schema→pydantic→StructuredTool 转换与 `_text_of` 展平（约 100 行）。
  工具返回内容的展平改由 `agent/runtime.py` 的 `_flatten` 统一处理（已有实现与测试）。
- 身份覆写保留：`wrap_tool_call` 钩子在真正执行前用 `runtime.context.user_id` 覆盖模型填的 `user_id`。
- 降级后必须冒烟验证的点（不当已确认事实）：服务端在 fastmcp 3.4.7 下 `mount(namespace=)` 行为一致、
  Streamable HTTP 端点可用、29 个工具名与参数不变、MCP 子进程不再因编码崩溃。

## 7. 状态与命名

- `AideState(AgentState)` 增加 `retrieved: list`（文档命中）与 `guardrail: dict`（本轮判定摘要）。
- 措辞规范（文档、日志、UI 一致执行）：
  - 禁止："自研 RAG""卖点""智能体矩阵""能力丰富"等宣传词。
  - 统一：`笔记检索`（note retrieval）、`向量库`（Chroma）、`执行节点`（graph node）、
    `外部工具`（MCP tools）。
  - 面板分区标题：`执行节点` / `笔记检索命中` / `工具` / `护栏` / `上下文`。
  - 节点标签直接用真实节点名，不再做中文美化映射（`Safety Guardrail.before_model` 原样显示，
    避免"标签好看但对不上日志"）。
- 前端过程帧不变（`tools_list / delta / node_update / tool_call / tool_output / completion`），
  新增一帧 `retrieval`（命中条数与标题列表），用于面板显示检索结果。

## 8. 错误处理

| 情况 | 行为 |
| --- | --- |
| embedding 模型缺失 | 启动告警；检索节点跳过注入，对话继续（现有 `rag_client` 测试夹具已按此语义） |
| Chroma 不可用 | 检索节点返回空命中并 WARNING；笔记 REST 返回既有错误结构 |
| MCP 连接失败 | `MultiServerMCPClient` 异常 → 空工具集 + WARNING，对话继续 |
| 护栏判定失败 | 放行并记录原因（沿用已实测策略） |
| 检索命中为空 | 不注入，不编造 |

## 9. 测试与验收

1. 离线：`pytest backend/tests -q` 全绿；`test_rag_recall.py` 断言不得放宽。
2. 新增离线用例：`retrieve` 命中写入 `state.retrieved`；`wrap_model_call` 注入的 SystemMessage
   不出现在 checkpoint 历史里；命中为空时不注入。
3. 端到端：`backend/scripts/e2e_langgraph_check.py` 在原 17 项基础上加两项断言——
   前置检索帧 `retrieval` 出现、"绿植浇水"这类问题**不调用任何工具**也能答对（证明召回不依赖模型主动检索）。
4. 回归：MCP 降级后重跑 29 个工具装载与天气/待办调用；REST 笔记检索契约不变。

## 10. 实施顺序（三步，每步独立可回归）

1. **检索层标准件化**：装 `langchain-chroma` / `langchain-huggingface`，改 `core/vector_core` 薄壳、
   `note_service`、`mcp-serve` 写入路径；交付重建脚本并执行；召回测试转绿。
2. **图与状态**：`AideState`、`before_agent` 检索、`wrap_model_call` 注入、`retrieval` 帧、
   措辞与面板分区收敛；离线用例 + e2e 扩项。
3. **MCP 标准件**：降 fastmcp 3.4.7 / mcp 1.30，换 `langchain-mcp-adapters`，删手写桥接，
   冒烟 29 工具与身份覆写。

## 11. 已知风险与未验证项

- fastmcp 3.4.7 与现有服务端其余 API 的兼容性只验证了 `mount` 签名，其余需第 3 步冒烟。
- ~~`langchain-chroma` 的相似度阈值语义~~ **已实测**：`similarity_search_with_relevance_scores`
  在 cosine 集合上返回 `1 - 余弦距离`，零词面查询"植物养护提醒"命中"绿萝浇水"得 0.54，
  与既有阈值 0.35 语义一致，不需要重标定。
- ~~`HuggingFaceEmbeddings` 加载本地目录的行为~~ **已实测并修掉一个真实缺陷**：检索层原先
  不自己 `load_dotenv`，导入顺序不对时 `local_embedding_model` 退回数据类默认的 HF hub 模型名，
  离线环境会触发五次联网重试、长时间挂起（实测卡住一次任务）。现由
  `core/retrieval/config.py` 显式加载 `backend/.env`，且 `build_embeddings` 对"像路径但目录不存在"
  的配置直接报错，只有 `org/name` 形式的 hub 模型名才允许联网。
- 前置检索每轮都跑，会给每轮增加一次 embedding 计算（本地 CPU，实测单条约几十毫秒，量级可接受）。

## 12. 不在本次范围

- 多代理/子代理（deepagents 式 subagents）、长期记忆 store、跨会话用户画像。
- MCP 服务端的资源归属校验（`note_id/todo_id` 越权问题，另案）。
- `AsyncSqliteSaver` 多用户并发压测。
