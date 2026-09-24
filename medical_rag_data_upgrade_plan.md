# Aide 医疗 RAG 数据与检索升级实施计划

> 2026-09-24 范围更正：用户明确要求只使用发布方提供的中文医疗语料。下文 MedlinePlus、USDA 及其他外文导入安排已停用；相关本地语料和研究索引切片已清理。当前保留 68 篇中文文档、88 个切片。新版候选与推荐见 `medical-rag-data/reports/chinese_sources_review.md`，等待用户选择中文来源后再接入。下文保留为历史规划，不再作为外文下载/导入指令。

版本：2026-09-23；范围：本机研究环境，面向中国大陆普通成年用户的健康科普与就医引导。正式对公众开放前的医疗专业审核暂不纳入本轮。

## 1. 决策与目标

本计划合并用户提供的《搜集并整理医疗、健康、食品营养、药物相互作用等开放数据》要求与 Aide 现有 Medical Health Agent 架构。附件中的疾病、症状、药品、食物、营养、相互作用、本体及中文语料都是**调查范围**；“至少 30 个候选数据源”指完成来源与授权调查，不等于首批导入 30 个库。

首批交付目标是：让常见健康问题能从更多真实、可追溯的资料中检索，并保持当前“健康对话每轮由统一 LLM 回答、命中时引用证据、未命中时仍能给保守建议”的体验。药物与食物相互作用、营养数值和知识图谱按各自证据与数据类型单独建设，不混作普通科普文本。

### 当前基线

- `backend/medical/source_corpus/` 有 86 条 `source_checked` 研究资料，含国家卫健委资料、MedlinePlus 健康主题及两条地方来源；现有说明见 `backend/medical/README.md`。`source_checked` 表示原文核对，不表示临床专业审核。
- 切片器 `backend/medical/chunking.py` 以 Markdown 标题分节、句子边界切分，默认 600 字符、同节 80 字符重叠；超长单句仍会硬切。
- 研究索引用 Chroma；检索用 BGE 稠密向量与 BM25，经加权 RRF 融合及 BGE reranker 重排。Medical Health Agent 通过 `medical_search` 工具取证据，继续共用现有 LiteLLM 配置。
- 不更换已工作的 embedding、reranker、Agent 路由及问答主链路；新增数据先建立影子索引并对照评估，再切换。

## 2. 数据准入：先调查，再入库

建立 `medical-rag-data/` 独立数据资产目录。原始大文件、密钥和可再下载的索引写入 `.gitignore`；在 Git 中保留脚本、清单、schema、少量可公开样本与评估报告。

```text
medical-rag-data/
  registry/datasets.csv, licenses.csv
  raw/<dataset>/<snapshot>/manifest.json, ...          # 本地原件，不提交大文件
  normalized/documents.jsonl, entities.jsonl, relations.jsonl
  rag/rag_documents.jsonl
  graph/nodes.csv, edges.csv
  scripts/discover.py, fetch.py, normalize.py, validate.py, build.py
  reports/dataset_report.md, license_report.md, ingest_report.md, eval_report.md
```

`datasets.csv` 至少调查 30 个候选来源；每项记录来源机构、原始 URL、官方 API/下载途径、更新频率、语言、格式、覆盖主题、管辖地区、拟用途、优先级、调查日期和证据链接。优先查官方网站、官方 GitHub 仓库、正式数据集页、原始论文和 LICENSE 文件。GitHub 实现只作为参考；仓库有代码许可证并不自动代表数据有同等许可。

`licenses.csv` 逐来源记录许可证名称、原文链接、商业使用、复制/再分发、翻译/改编、RAG 检索展示、模型训练、署名要求、注册要求、数据项级例外、核查日期。可用性分别标成 `OPEN`、`RESEARCH_ONLY`、`NON_COMMERCIAL`、`REGISTRATION_REQUIRED`、`RESTRICTED`、`UNKNOWN`；具体权利使用 `yes/no/unknown`，不得由“免费访问”推断为“可导入”。授权不明者只进调查台账，不进入默认可回答索引。研究实验与未来产品复用分别登记。

数据质量另设独立维度：机构权威性、内容更新、证据类型、适用地区、中文可用性、可追溯性、适用人群。**权威来源不等于每条医学结论有高级别临床证据**。记录指南、系统综述、试验、说明书、科普或社区问答的原始类型；社区问答和考试题仅用于查询表达分析、离线评估或许可明确的独立实验，不直接作为医疗建议依据。

### 已核查的首批候选

| 来源 | 计划用途 | 准入结论/待查点 |
| --- | --- | --- |
| MedlinePlus Health Topic XML | 第一批可复现的疾病、症状、预防主题扩容 | 官方提供批量 XML；**仅健康主题摘要**按其使用说明处理。其 A.D.A.M. 医学百科和 AHFS 药物专论另有版权，不能整体照搬。已在 Aide 有导入适配器。见 [XML](https://medlineplus.gov/xml.html)、[使用条款](https://medlineplus.gov/about/using/usingcontent/)。 |
| 国家卫健委中文科普与官方材料 | 中国用户的中文高频问答优先内容 | 先逐站点、逐文件核查使用条件和原文版本；授权不清时保留链接和调查记录，暂不批量复制。现有 66 条已在研究索引，须补做来源与授权台账。 |
| PMC Open Access 子集 | 后续专题证据检索，不直接混入大众科普主索引 | 并非所有 PMC 全文可复用；每篇核查具体许可证。仅用官方允许的 OAI-PMH、E-Utilities、BioC 或云数据途径获取。见 [PMC 官方说明](https://pmc.ncbi.nlm.nih.gov/tools/openftlist/)。 |
| DailyMed / openFDA drug label | 后续药品说明书与警示信息候选 | DailyMed 提供当前 SPL v2 API、SET ID 与版本历史；先核查具体内容重用条件、美国适用性及品牌/成分映射，做小样本试点。见 [DailyMed API](https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm)、[openFDA 下载](https://open.fda.gov/apis/drug/label/download/)。 |
| USDA FoodData Central | 后续食物营养数值试点 | 官方数据为 CC0；保留 FDC ID、数据类别、单位、每 100 g 换算依据和更新时间。优先结构化查询。见 [官方 API 与许可](https://fdc.nal.usda.gov/api-guide/)。 |
| RxNorm / MONDO / HPO 等 | 仅用于实体标准化和跨源映射 | RxNorm 完整发布涉及 UMLS 许可和部分第三方词表，不能一概视作无条件开放；可先调查无额外许可的 Current Prescribable Content 子集。见 [NLM 官方说明](https://www.nlm.nih.gov/research/umls/rxnorm/overview.html)。本体还须逐项核查版本与许可证。 |
| FooDrugs、KG-DFI、DFI Corpus、OpenCMKG、D2hKG、Huatuo、cMedQA、CMExam | 候选关系数据或评估数据 | 逐项核对原始仓库/论文/许可证/数据下载与事实出处；未经核查的食药关系不进入回答链路。 |

## 3. 数据契约与存储

### 3.1 来源与文档

保持现有 `MedicalDocument` 兼容。新增独立来源注册与规范化记录，不把图谱关系硬塞进文档 `body`。规范化文档至少有：`dataset_id`、`source_doc_id`、`version`、`source_url`、`source_org`、`language`、`jurisdiction`、`audience`、`content_type`、`evidence_type`、`license_id`、`rights_scope`、`published_at`、`collected_at`、`updated_at`、`source_sha256`、`withdrawn`、`review_status`、`section_path`、`text`。缺失字段显式为 `null`，不能虚构日期或“已审核”。

`rag_documents.jsonl` 每条为证据片段，追加 `chunk_id`、`parent_doc_id`、`char_start/end` 或 XPath/章节 ID、`chunker_version`、`embedding_version`、`title`、`source_locator`。`chunk_id` 用稳定文档 ID + 原文版本 + 片段定位生成，支持差量更新和删除；从片段必须能回溯到原件、数据集、许可证和官方 URL。

### 3.2 实体与关系

先定义 `Disease`、`Symptom`、`DrugIngredient`、`DrugProduct`、`Food`、`Nutrient`。实体主键采用“来源命名空间:原始 ID”；跨库同义词通过带置信度和证据的 `crosswalk` 连接，中文名相同不自动合并。关系字段至少有主语、谓词、宾语、方向、适用人群、条件、剂量/单位、地区、证据类型、原文定位、来源版本、审查状态和否定/争议标记。`Food–Drug Interaction` 和 `Disease–Food` 是有条件、有出处的候选关系，禁止由 LLM 自行编造。

首版 `nodes.csv` / `edges.csv` 加 SQLite/JSONL 即可；只有多跳问题在真实测试中有明确收益，再考虑图数据库及 GraphRAG。传统“食物相克”说法与经证据支持的相互作用分开标识，不把民俗搭配表当成禁忌医嘱。

### 3.3 数据版本与更新

每次拉取生成不可变快照清单：请求 URL、获取时间、源版本、ETag/Last-Modified、文件大小、SHA256、获取脚本版本、许可证快照。导入器必须幂等；记录新增、修改、撤回、失败项。原件只读保存；更新时生成新版本而非原地改写。源文撤回或许可收紧要能反向定位所有片段并从研究索引移除。

## 4. 按数据类型设计切片与检索

| 类型 | 切片策略 | 检索/回答处理 |
| --- | --- | --- |
| 官方中文科普 HTML/PDF | 标题、段落、清单为边界；危险信号、适用人群、就医时机、注意事项保持完整；PDF 留页码 | 保留原文链接和发布日期，中文问答优先；相同主题去重但不抹去来源差异 |
| MedlinePlus XML | 每个 health-topic 的摘要及结构化主题关联单独解析；先按语义段落，再按完整句聚合；中文别名只用于召回，不把英文本体冒充中文原文 | 英文原文可引用；中文输出需忠实转述，标明来源，不自动引入其外链的第三方内容 |
| DailyMed SPL | 依官方 section code 保留适应症、禁忌、警告、相互作用、不良反应等章节；表格、剂量和条件原子化 | 按具体成分、剂型、产品、版本检索；美国说明书只作适用性明确的证据，不直接给中国用户处方建议 |
| PMC OA JATS | 摘要、方法、结果、讨论及表格分别处理；保留 PMID/PMCID、期刊、年份、文章许可证 | 作为专题证据层；结果和讨论分开，不把研究相关性写成临床因果 |
| USDA FDC | 不将全部数值表随机切片；按 FDC ID、食物类型、营养素、单位做结构化行 | SQL/API 精确查询与单位换算，必要时只把解释性文字向量化 |
| 本体/KG | 节点与有出处的边分别存储，保留方向、否定和条件 | 实体消歧/关系候选；不作为独立医学建议来源 |

通用切片器保留为回退，但修复超长句硬切，增加列表、表格、否定、剂量/单位、警示语不拆散的测试。切片大小按源类型与评测调节，不承诺一套固定字符数适用于所有来源。

查询侧保持现有 BGE + BM25 + RRF + rerank；新增类型/地区/许可/有效期过滤、药物成分和食物实体消歧、必要的路由：科普走文本索引，营养数值走结构化查询，药物相互作用先查说明书和证据化关系。最终仍由 Medical Health Agent 将问题、受控对话上下文与检索结果交给统一 LLM；提示词要求区分“检索证据”和“一般安全提示”，表达自然，并提供可核验出处。

## 5. 分阶段实施与验收

| 阶段 | 具体工作 | 完成标准 |
| --- | --- | --- |
| P0 基线与风险台账 | 冻结当前 86 文档/索引和现有回归集；盘点源代码、许可证、导入状态；先核查 30 个候选源并写 `datasets.csv`、`licenses.csv`、两份调查报告 | 候选数 ≥30；每项都有可核验链接和明确状态；对“已收集”与“可作为回答证据”分别统计；未知授权没有被默认放行 |
| P1 数据底座 | 加入原件快照、统一规范化 schema、校验器、增量/撤回机制；补现有 86 文档的来源台账；建立影子索引 | 同一源重跑无重复；修改/撤回能正确更新；任一片段可追溯到来源、版本和许可证；旧研究索引可回滚 |
| P2 **首个扩容试点** | 复用 `import_medlineplus.py`，仅导入 MedlinePlus 健康主题 XML 中高频成年人症状、就医、预防主题；先列覆盖清单，再按主题扩展约 50–100 条，不引入百科/药物专论；并行调查可合法使用的官方中文来源 | 新主题数、语言、映射、失败率和覆盖增量有报告；旧集与影子集同题对照，来源显示正确；无第三方内容混入 |
| P3 中文资料与源适配 | 对许可已明确的中文官方资料按页面/章节做差量导入；加入 MedlinePlus、HTML/PDF 的源专属 chunker；针对症状危险信号与否定条件优化 | 高频中文问题覆盖显著增加；危险信号/单位/否定没有被切碎；引用能打开原始段落或页码；没有由英文别名引发的错误对齐 |
| P4 药品与营养独立试点 | 选少量明确版本的 SPL 说明书与 FDC 食物记录，落地结构化实体、SQL 查询和证据化关系；先不做广泛食药相互作用建议 | 药品能按成分/剂型/版本定位；营养能按单位正确还原；缺证据的关系被拒绝；地区不适用时明确提示 |
| P5 图谱与专题评估 | 从已核准数据生成 `nodes.csv`/`edges.csv`；建立多跳评测，判断是否值得引入 GraphRAG | 图谱边 100% 有来源定位；多跳问题相对混合检索有可重复的增益才接入在线链路，否则保留离线资产 |

P0/P1 是 P2 的数据准入前置；P3 依授权结果进行。P4、P5 不阻塞高频健康问答扩容。每阶段完成后先在影子索引比较，再切换本地研究索引；上线前保留上一版快照和一键回滚配置。

## 6. 评测与发布门槛

先固定现有回归集，再新增一套不参与阈值调整的中文盲测集，按症状、运动营养、药品信息、食药相互作用、错别字、多轮追问、否定、地区适用性分层。报告至少包括：主题覆盖、Recall@5、nDCG@10、误召回、无答案正确率、引用可追溯率、证据支持率、危险信号漏报、P50/P95 检索耗时、更新/撤回一致性。用同一批题比较旧索引与影子索引，不以文档数或 chunk 数单独宣布升级成功。

本机切换门槛：旧有关键场景无回归；新增主题可检索；引用全部指向实际返回的原件；任何无授权内容、无来源药物相互作用或高风险警示丢失均阻断切换。医学专业审核仍是未来面向公众开放的独立发布门槛。

## 7. 本轮不做的事与后续选择

- 不把 30 个候选源等同于 30 个已接入源；调查成果会明确 `discovered`、`downloaded`、`normalized`、`indexed`、`answer_eligible` 状态。
- 不把 PMC 全站、MedlinePlus 所有栏目、社区问答、传统食物相克表或 UMLS 全量数据直接灌入向量库。
- 不为“GraphRAG”先引入新的图数据库。先用可追溯的实体/关系文件验证问答收益。
- 不改成独立医疗 LLM API；继续沿用统一 Agent 和 LiteLLM 链路。

## 8. 第一轮开发顺序

1. 创建来源/许可证台账和 schema，完成 30 项候选调查；把已有 86 条反向登记为基线。
2. 实现原件快照、许可准入和 normalized → chunk → shadow Chroma 的可复现流水线。
3. 扩容 MedlinePlus health-topic XML 的 50–100 个高频主题，补中文别名但保留英文原文身份。
4. 跑冻结评测并修复真正暴露的切片、映射和引用问题，然后切换本机研究索引。
5. 在中文来源许可明确后，按同一流水线接入首批官方中文专题；随后推进 SPL/FDC 小样本。

这使第一轮能交付实质性知识覆盖，同时为药物、营养和 GraphRAG 留下明确而可验证的数据契约。
