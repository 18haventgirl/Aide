# 中文 RAG 扩容工程验收（2026-09-26）

## 决策及范围

华佗 Lite 的 5,000 条候选用于离线检索研究，不直接接入 Medical Agent 回答。全量来源审计发现 5,000 条均缺少逐条医学原文 URL，能够核实并获准用于回答的条目为 0。抽查又发现筛选遗漏的具体药物剂量及缺依据建议，因此不以相似度或 rerank 分数替代内容核对。

正式运行链路继续读取原有可追溯中文 corpus。已有 BGE + BM25 + RRF + reranker 实现得到复用和修复；本轮不新增医疗专用 LLM，也不修改用户密钥或模型地址。

## 开源技术选择

- 复用 [FlagEmbedding 官方项目](https://github.com/FlagOpen/FlagEmbedding) 的 BGE embedding / cross-encoder 模型路线，以及项目已有的固定版本本地推理封装。
- [Huatuo Lite 数据卡](https://huggingface.co/datasets/FreedomIntelligence/Huatuo26M-Lite) 描述社区问题和模型改写回答；其数据自评分不是医学复核。
- SQLite FTS5 + jieba 提供磁盘关键词召回，Chroma 保存 512 维 BGE 向量。无需增加框架、外部数据库服务或下载语言模型。

## 实现与隔离

1. 读取前校验规范化样本 SHA、向量模型权重 SHA、FTS 与 Chroma 样本一致性、索引记录数；拒绝缺失/不完整/混版索引。
2. 每路召回 24 条，ID 去重，加权 RRF（dense 0.6 / lexical 0.4，常数 60）；前 12 条交给现有 BGE-reranker-base，batch=1，最大长度 512。
3. 召回与批量重排分别在两个进程执行，避免两个模型长期同时占内存。启动资源门槛及异常保持显式；不后台关闭用户程序。
4. 重排返回异常、数量不匹配、NaN、Infinity 或越界分数时，返回原始 RRF 顺序并标记 fallback；所有结果始终 `answer_eligible=false`。
5. 试验模块没有注册为 Agent 工具。Medical Agent 的检索、来源元数据和统一 LiteLLM 模型链路保持现有接口。

## 50 题检索对照

| 模式 | Recall@5 | MRR@5 | nDCG@5 |
| --- | ---: | ---: | ---: |
| BGE 向量 | 0.9000 | 0.8167 | 0.8377 |
| BGE + FTS/BM25 + RRF | 0.8000 | 0.6790 | 0.7094 |
| RRF + BGE reranker | 0.9000 | 0.8283 | 0.8465 |

50/50 均实际执行重排。重排进程峰值工作集约 939.6 MiB。

这些是根据候选问题改写的开发题，非独立盲测。相关 ID 只评价问题匹配，不表示答案正确；正例列表也不穷尽。多正例 Recall 按命中数量/正例数量计算，不用任意命中率冒充召回率。不以该数据集调整线上全局门槛。

结果不支持默认启用单纯 RRF：它在这套题上退步。试验查询默认纯向量，rerank 为显式选项；重排在本开发集只带来轻微排序改善，不宣传为全面提升。

## 现有运行链路修复

- 重排不可用时，候选先按融合分排序，避免按候选插入顺序返回。
- 检查所有重排分数的数量、有限性和范围，异常时完整回退。
- 使用数值稳定的 sigmoid，避免极端负 logit 溢出。
- 查询时增加中文语言过滤，防止旧索引遗留的显式非中文记录进入回答。
- 移除 README 中已停用英文语料的复现命令。

## 验证与复现

数据及详细运行结果保存在 D 盘既有版本目录的 `indexes/pilot-5000-adult-general-screen-v1`，不进入 Git。样本 SHA：`c4e15654027aa6c17610ece61d44d53b6ed8dba5710bd48b50260d83de7e52da`。

在 backend 目录执行：

```powershell
.\.venv\python.exe -X utf8 -m medical.pilot_evaluate audit
.\.venv\python.exe -X utf8 -m medical.pilot_evaluate collect
.\.venv\python.exe -X utf8 -m medical.pilot_evaluate score
.\.venv\python.exe -X utf8 -m medical.pilot_retrieval --query "成年人如何改善睡眠" --mode dense
.\.venv\python.exe -X utf8 -m medical.pilot_retrieval --query "成年人如何改善睡眠" --mode rerank
.\.venv\python.exe -X utf8 -m unittest tests.test_pilot_retrieval tests.test_huatuo_lite tests.test_medical_rag tests.test_medical_runtime tests.test_medical_grounding tests.test_medical_data_registry
```

37 项相关自动测试及 2 项现有 Agent 协作测试通过。覆盖中文过滤、筛选与索引、重排失效、分数异常、来源元数据和缓存。旧评估器把多正例的任意命中率记作 Recall，现已按真正的 Recall/nDCG 修正并标记 `metric_version=multi_relevant_v2`，旧报告不能直接跨版本比较。华佗对照的 MRR 统一截断在 5，避免各模式候选池长度不同影响比较。

### 真实 DeepSeek 集成验收

使用项目统一 LiteLLM model factory、现有 Medical Agent 提示词和真实 medical_search 实现，独立 Runner 执行合成问题；不读取用户聊天，不写入健康记录。连接为本机已配置的官方 `api.deepseek.com`，模型 `deepseek-flash`，未更改配置。

| 场景 | 检索工具调用 | 实际模型 token 总量 | 生成最终回答 |
| --- | ---: | ---: | --- |
| 可追溯中文资料命中 | 1 | 4,670 | 是 |
| 注入空检索结果 | 1 | 3,435 | 是 |
| 注入检索不可用状态 | 1 | 3,009 | 是 |

命中场景使用真实本地检索，确认无 HTL 候选进入。另两种是故障注入，模型请求仍是真实请求。共计 11,114 tokens。验收确认模型继续回答，不代表对每句医学事实的专业审核；部分未命中回答仍会产生模型常识中的具体数字，不能当成知识库支持的结论。

验证范围为 Agent → 工具函数 → 本地检索 → 官方 LLM；没有经过 MCP HTTP 传输、用户鉴权、会话持久化或浏览器 UI。完整记录在本地 `reports/agent_live_verification.json`。可用 `medical.verify_agent --live --output <文件>` 显式复现，会产生 API 用量。

## 发布与回退

本轮不将华佗候选发布到回答索引，不增加自动晋级路径。现有库可通过 `MEDICAL_USE_RERANKER=false` 使用已校验的融合回退；该设置需重启服务生效。代码提交可独立回退，语料和用户笔记/会话数据库不需要迁移。

下一轮内容扩容应按评估暴露的缺口采集中文原始资料，保留发布日期、发布机构、原文哈希和定位，核对后按既有 source_checked 本机研究流程入库。缺乏来源的华佗答案不改名伪装成官方资料。

## 现有中文库回归与剩余缺口

旧 33 题保持原预期（包括已删除的 MPLUS 文档）重跑，使用修正后的多正例指标：15 道支持类问题 Recall@5=0.644、MRR=0.689、nDCG@5=0.633；8 道不可回答题拒绝率 1.0，5 道紧急检测通过率 1.0，5 道追问 Recall@5=0.9。平均检索约 3385 ms，P95 4089 ms，包含模型冷启动，因此不可与纯向量热查询的 18–26 ms 直接比较。

完全未命中预期的题为 VS02 咽痛、VS04 头痛、VS05 腹痛、VS07 腹泻。该报告是覆盖缺口基线，不能用它声称扩容已完成或零回归；旧英文文档预期没有被删除来抬高分数。

已经定位四篇中文政府发布的补充候选，记录于 `registry/chinese_gap_candidates.json`。正常直连与本机代理下载均收到 HTTP 403，未保存可验原文，故未导入。搜索结果摘要不作为可追溯原始快照。结论：检索工程、离线评估及 Agent/模型集成验证已完成；可靠中文证据扩容尚未完成。
