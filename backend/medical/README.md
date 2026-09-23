# Aide 医疗知识 RAG：本机研究版

本模块在 Aide 的“健康知识”模式中提供来源可追溯的中文健康科普。范围是中国大陆成年人一般健康知识与保守就医引导。它不提供个人诊断、处方、剂量或改药建议。尚未计划公开上线。

## 数据与模型

- `source_pipeline.py` 对照 2024 年正式《健康素养 66 条》与国务院网站托管的正式释义 PDF，生成 66 条记录；另有北京、广州卫健委各一条常见症状就医资料。原文及 SHA256 记在 `source_downloads/` 和 `source_corpus/source_manifest.json`。原文下载目录被 Git 忽略。
- `source_corpus/` 当前线上研究基线包含 86 条 JSON 资料，均为 `source_checked`，表示机器核对原文，**不是医疗专业审核**。新一批 MedlinePlus 主题先在独立影子索引评估，通过后才同步到这里。正式公共索引仅接纳 `clinician_reviewed` 且未过期、未撤回的资料。
- `import_medlineplus.py` 从固定版本的 MedlinePlus Health Topic XML 中选择原有 18 个高频主题和新选的 50 个运动、睡眠、慢病预防、营养等主题。正文保留官方英文，中文标题与别名和官方摘要位于同一检索片段，避免召回只有标签而没有医学内容的片段。新主题尚未通过影子评估前不会修改运行中的研究索引。
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
.\.venv\python.exe -m medical.download_medlineplus
.\.venv\python.exe -m medical.import_medlineplus
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

仓库根目录的 `medical-rag-data/registry/datasets.csv` 列出 34 个候选源，`licenses.csv` 单独记录使用权利。候选数不等于已导入数。新增来源须通过 `medical.data_registry` 的 fail-closed 检查；当前扩容只使用 MedlinePlus 健康主题摘要，不复制其受版权保护的百科或药物专论。

```powershell
cd backend
.\.venv\python.exe -m medical.data_registry
.\.venv\python.exe -m medical.export_medlineplus_assets
.\.venv\python.exe -m medical.shadow_medlineplus --report ..\medical-rag-data\reports\medlineplus_shadow_2026-09-24.json
```

固定的 2026-09-19 官方 XML 压缩包在被 Git 忽略的 `source_downloads/`。导出器生成 68 条主题文档、`normalized/` 与 `rag/` JSONL 和 SHA256 清单；其中 50 条是新增主题。中文名称/别名只用于召回，英文官方摘要仍是证据正文。MedlinePlus 的 `source_published_at` 记录 XML `date-created`，快照日期另存 `source_version`。影子评估在独立 Chroma 目录中构建基线与扩容索引，不触碰运行中的研究 collection。
