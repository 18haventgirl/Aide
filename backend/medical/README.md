# Aide 医疗知识 RAG：本机研究版

本模块由 Aide 的 Triage 路由至 Medical Health Agent，提供来源可追溯的中文健康科普；前端不再依赖“健康知识”开关。范围是中国大陆成年人一般健康知识与保守就医引导。它不提供个人诊断、处方、剂量或改药建议。尚未计划公开上线。

## 数据与模型

- `source_pipeline.py` 对照 2024 年正式《健康素养 66 条》与国务院网站托管的正式释义 PDF，生成 66 条记录；另有北京、广州卫健委各一条常见症状就医资料。原文及 SHA256 记在 `source_downloads/` 和 `source_corpus/source_manifest.json`。原文下载目录被 Git 忽略。
- `source_corpus/` 当前本机研究索引包含 72 条中文 JSON 资料、95 个切片（2026-09-28 增补后），均为 `source_checked`，表示原文核对，**不是医疗专业审核**。新增流感、咽喉、头痛、腹泻四篇限定范围摘录，验收见 `medical-rag-data/reports/chinese_symptoms_acceptance_20260928.md`。正式公共索引仅接纳 `clinician_reviewed` 且未过期、未撤回的中文资料。
- 2026-09-24 按用户要求改为仅使用中文原文。MedlinePlus 的 68 篇英文文档与 562 个切片已撤下，原始下载与衍生数据已清理；相关脚本保留作历史参考，下载和导入入口被语言策略阻止。原文语言需准确写入文档的 `language`，不得通过中文标题把英文正文标记为中文。
- 向量模型为本机运行的 `BAAI/bge-small-zh-v1.5`，固定模型 revision 和权重 SHA256。模型文件在 `models/`（Git 忽略）。研究与正式索引使用分开的 Chroma collection。
- 检索先分别取得 BGE 稠密候选和全库 jieba/BM25 关键词候选，用加权 RRF 合并后，将前 8 个片段交给本机 `BAAI/bge-reranker-base` 交叉编码器重排。最后按相关性门槛过滤，并限制单份文档最多占两个片段。重排模型固定 revision 和权重 SHA256；模型缺失或推理失败时会退回经过门槛控制的混合排序，不会让检索服务整体中断。
- 医疗 Agent 与其他 Agent 共用 Aide 的 LiteLLM 模型配置 `OPENAI_API_KEY`、`OPENAI_API_BASE_URL` 和 `OPENAI_CHAT_MODEL`。每个健康问题先调用一次 `medical_search`，把检索证据与对话问题一起交给同一个 LLM；首次结果明确未覆盖且确需换一种含义检索时，最多再调用一次。旧的 `MEDICAL_LLM_*` 独立生成路径已移除。
- 工具返回的来源、覆盖状态、紧急程度和问题范围由后端确定性解析，随最终消息元数据持久化并交给前端来源卡片展示，不依赖 LLM 在正文中复制链接。证据原文和检索分数不会写入消息元数据。
- 检索事件写入 `backend/logs/medical_retrieval.jsonl`，只记录命中文档 ID、候选数量、重排状态、最高相关分和各阶段耗时，不保存用户问题。分数和门槛只用于本机排序调试，不能解释为医学可信度。
- 紧急情况和明确要求个人诊断、处方或改药的请求在检索前拦截。聊天记录中的健康问题保存在 Aide 原有会话数据库中；用户可在会话列表删除会话，后端会在同一事务中删除其消息并清除本进程会话缓存。数据库备份或外部模型服务已接收的数据不在这个删除操作范围内。
- MCP 启动时预热 BGE 和重排模型。相同查询使用默认 60 秒、最多 128 项的进程内缓存；缓存键是查询摘要，不保存问题原文。短追问可携带最多 500 字、仅由用户明确说出的症状、时间、部位、测量值和用药事实作为检索上下文。

## 复现

在 `backend` 目录、已安装 `requirements.txt` 及 `.env` 后执行：

```powershell
.\.venv\python.exe -m medical.download_bge
.\.venv\python.exe -m medical.download_reranker
.\.venv\python.exe -m medical.download_sources
.\.venv\python.exe -m medical.source_pipeline
.\.venv\python.exe -m medical.cli validate --corpus medical/source_corpus
.\.venv\python.exe -m medical.cli sync --research --corpus medical/source_corpus
.\.venv\python.exe -m medical.evaluate --cases medical/eval_cases_research.json --k 5
.\.venv\python.exe -m medical.evaluate --cases medical/eval_cases_validation_v1.json --k 5
.\.venv\python.exe -m medical.evaluate --cases medical/eval_cases_expansion_v1.json --k 5
.\.venv\python.exe -m unittest discover -s tests -p 'test_medical*.py' -v
```

`download_sources` 只获取白名单 URL，并按版本清单中的 SHA256 校验；官方页面若已变动会停止，需要人工核对新版本。`source_pipeline` 再核验关键标题、条数及正文。设置 `NODE_ENV=development` 和 `MEDICAL_RESEARCH_MODE=true` 才能在 Aide 界面使用研究索引。不要把任何 API 密钥加进 Git。

开发集是 111 道手工编写的本机测试题，包含 61 道有依据问题、20 道无依据问题、20 道紧急问题和 10 道多轮追问，并包含容易被泛化词污染的针对性反例。另有 33 道冻结回归集和 10 道新增主题覆盖集。详见 `eval_report_research.md` 与 `eval_report_validation_v1.md`。除 Recall@K 和 MRR 外还记录 nDCG、指定错误文档进入前 K 的比例及检索耗时。冻结集中的失败项已用于修正规则，因此它现在是回归集，仍需未来从外部获得真正独立的盲测集。

可调参数：`MEDICAL_DENSE_CANDIDATES`、`MEDICAL_LEXICAL_CANDIDATES`、`MEDICAL_RERANK_CANDIDATES`、`MEDICAL_RERANK_MIN_SCORE`、`MEDICAL_MAX_CHUNKS_PER_DOCUMENT`、`MEDICAL_RETRIEVAL_CACHE_TTL_SECONDS` 和 `MEDICAL_RETRIEVAL_CACHE_SIZE`。`MEDICAL_USE_RERANKER=false` 可验证降级路径。

## 数据扩容与影子评估

### 华佗 Lite 离线试验（2026-09-26）

5,000 条候选已经完成 SQLite FTS5 与 BGE 向量建库。候选缺少逐条医学原始来源，均为 `answer_eligible=false`，不注册到 Medical Agent，不进入既有回答 collection。完整报告见仓库 `medical-rag-data/reports/huatuo_lite_pilot.md`。

可重复执行以下命令完成来源审计、BGE/BM25 加权 RRF、BGE cross-encoder 重排对照：

```powershell
.\.venv\python.exe -X utf8 -m medical.pilot_evaluate audit
.\.venv\python.exe -X utf8 -m medical.pilot_evaluate collect
.\.venv\python.exe -X utf8 -m medical.pilot_evaluate score
```

召回和重排分进程执行，释放 embedding 模型后再加载 reranker，降低同时驻留内存。重排使用已有固定版本 BGE-reranker-base，batch=1，最多 12 个候选。异常分数或推理失败明确标记为 fallback，不能报告成重排成功。模型分数不是医疗可信度。

`eval_cases_huatuo_v1.json` 的 50 道题是根据候选问题人工式改写的开发集，相关 ID 表示问题匹配，不认可其回答。正例不穷尽、同一主题有两种问法；不能作为独立盲测或临床效果报告。原有包含已删除英文文档的评估集保持原样，以暴露覆盖缺口。

仓库根目录的 `medical-rag-data/registry/datasets.csv` 保存原候选调查台账，`licenses.csv` 单独记录使用权利。新增来源须通过 `medical.data_registry` 的许可与中文语言检查。中文候选比较见 `medical-rag-data/reports/chinese_sources_review.md`。

```powershell
cd backend
.\.venv\python.exe -m medical.data_registry
```

旧 MedlinePlus 评估报告仅用于历史追溯。旧评测中的外文文档预期仍保留，不能通过修改预期掩盖中文知识覆盖缺口；扩容后的中文库需要重新评测。

## 结构化营养数据试点

USDA 英文营养数据试点已停用并清理，历史说明见 `medical-rag-data/reports/usda_foundation_pilot.md`。后续选择中文营养资源重新开展。
