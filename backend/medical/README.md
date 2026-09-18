# Aide 医疗知识 RAG：本机研究版

本模块在 Aide 的“健康知识”模式中提供来源可追溯的中文健康科普。范围是中国大陆成年人一般健康知识与保守就医引导。它不提供个人诊断、处方、剂量或改药建议。尚未计划公开上线。

## 数据与模型

- `source_pipeline.py` 对照 2024 年正式《健康素养 66 条》与国务院网站托管的正式释义 PDF，生成 66 条记录；另有北京、广州卫健委各一条常见症状就医资料。原文及 SHA256 记在 `source_downloads/` 和 `source_corpus/source_manifest.json`。原文下载目录被 Git 忽略。
- `source_corpus/` 的 68 条 JSON 资料为 `source_checked`，表示机器核对原文，**不是医疗专业审核**。仅能进入开发环境的研究索引。正式公共索引仅接纳 `clinician_reviewed` 且未过期、未撤回的资料。
- 向量模型为本机运行的 `BAAI/bge-small-zh-v1.5`，固定模型 revision 和权重 SHA256。模型文件在 `models/`（Git 忽略）。研究与正式索引使用分开的 Chroma collection。
- 检索使用章节切片、BGE 向量和研究版暂定距离门槛。门槛 `MEDICAL_RESEARCH_MAX_DISTANCE` 默认 0.50。另用 [jieba](https://github.com/fxsjy/jieba) 与 [rank-bm25](https://github.com/dorianbrown/rank_bm25) 补充强关键词命中的片段；保留向量结果原有排序。设置 `MEDICAL_RESEARCH_USE_LEXICAL=false` 可复测纯向量基线。这些门槛来自同一批本机题，不能视作医学可信度分数，也不能直接用于公开产品。
- 生成使用单独的 `MEDICAL_LLM_*` 配置。默认允许官方 OpenAI、DeepSeek 或本机地址。当前本机配置为 DeepSeek。发送给模型的是本轮问题、最多四轮简短上下文与最多五条证据。输出必须为结构化陈述并引用已提供的证据编号；未知编号、异常和模型不可用时拒绝生成。
- 紧急情况和明确要求个人诊断、处方或改药的请求在检索前拦截。聊天记录中的健康问题保存在 Aide 原有会话数据库中；用户可在会话列表删除会话，后端会在同一事务中删除其消息并清除本进程会话缓存。数据库备份或外部模型服务已接收的数据不在这个删除操作范围内。

## 复现

在 `backend` 目录、已安装 `requirements.txt` 及 `.env` 后执行：

```powershell
.\.venv\python.exe -m medical.download_bge
.\.venv\python.exe -m medical.download_sources
.\.venv\python.exe -m medical.source_pipeline
.\.venv\python.exe -m medical.cli validate --corpus medical/source_corpus
.\.venv\python.exe -m medical.cli sync --research --corpus medical/source_corpus
.\.venv\python.exe -m medical.evaluate --cases medical/eval_cases_research.json --k 5
.\.venv\python.exe -m unittest discover -s tests -p 'test_medical*.py' -v
```

`download_sources` 只获取白名单 URL，并按版本清单中的 SHA256 校验；官方页面若已变动会停止，需要人工核对新版本。`source_pipeline` 再核验关键标题、条数及正文。设置 `NODE_ENV=development` 和 `MEDICAL_RESEARCH_MODE=true` 才能在 Aide 界面使用研究索引。不要把 `MEDICAL_LLM_API_KEY` 加进 Git。

评估集是 100 道手工编写的本机测试题，包含 50 道有依据问题、20 道无依据问题、20 道紧急问题和 10 道多轮追问。详见 `eval_report_research.md`。Recall@K 是标注文档是否被检索到；查询量与命中量并不是召回率。距离门槛、拒答及紧急识别仍需独立且经医学专业人员审定的评估集。引用编号仅验证输出引用了已检索资料，不能自动证明每个医学陈述正确。
