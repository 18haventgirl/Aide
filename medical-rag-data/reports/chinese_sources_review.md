# 中文医疗语料候选与范围更正

核查日期：2026-09-24。用户要求仅使用发布方提供的中文正文；不再以英文正文加中文别名扩充知识库。当前任务是清理外文语料并展示候选，新候选尚未导入。

## 推荐选择

优先用国家卫健委及地方卫健委的中文专题、官方问答与健康科普扩充回答证据。开源数据中先考察 Huatuo-26M 的百科子集和 Huatuo-Lite，但需经过抽样、去重、来源恢复和不适宜内容过滤；不应直接导入全量问答。若目标是提升检索匹配而非增加证据，可选 cMedQA2。若做结构化关系实验，可选 OpenCMKG。

| 候选 | 已核查内容与获取方式 | 适合 Aide 的用途 | 局限与使用条件 |
|---|---|---|---|
| 国家卫健委中文科普、官方问答 | [健康科普辟谣平台](https://www.nhc.gov.cn/kppypt/index.shtml)，包括合理用药、营养、慢性病、运动等分类；HTML 页面 | 核心回答证据；按主题采集，保存日期、发布机构、原文链接 | 不是完整可下载数据集；本次未找到统一开放全文 API；不能把可阅读等同于全站开放许可，需逐项记录使用条件 |
| 国家卫健委食养指南及问答 | [2023 年官方发布页](https://www.nhc.gov.cn/sps/c100088/202301/f01895a06c5349ef999f25da833c166d.shtml)，提供高脂血症、高血压、糖尿病等 PDF 与问答 | 营养、饮食、慢病健康管理；章节与表格分别提取 | 发布页鼓励参照使用和科普宣传，但不是全站 CC 授权；保留适用人群；现代营养与传统食养条目分别标记 |
| 中国疾控中心中文健康科普 | [食物营养栏目](https://www.chinacdc.cn/jkkp/yyjk/swyy/)；网页文章 | 营养与预防知识补充 | 栏目也包含转载内容，需要检查原始作者、发布时间和转载条件 |
| Huatuo-26M / Huatuo-Lite | [作者仓库](https://github.com/FreedomIntelligence/Huatuo-26M/blob/main/README_zh.md)、[百科数据](https://huggingface.co/datasets/FreedomIntelligence/huatuo_encyclopedia_qa)、[Lite 数据](https://huggingface.co/datasets/FreedomIntelligence/Huatuo26M-Lite)；JSON/Hugging Face datasets。百科 train 约 36.2 万条，Lite 约 17.8 万条；项目整体宣称超过 2600 万问答 | 最值得优先抽样考察的现成中文问答候选；可做问题覆盖分析、检索实验，再筛选适合的正文 | 项目及数据卡声明 Apache-2.0；上游聚合内容来源仍需核对。咨询子集答案是 URL，不等于 2600 万条完整可用答案。公开样例含缺来源、过度推断和不适宜建议，不能直接当指南 |
| cMedQA2 | [作者仓库](https://github.com/zhangsheng93/cMedQA2)；ZIP 内 CSV，108,000 个问题、203,569 个答案及固定数据划分 | 中文问题匹配、检索器/重排器评估 | README 明确非商业研究用途；仓库 GPL 标签不能覆盖该数据限制；社区回答不作为高等级事实依据 |
| OpenCMKG | [作者仓库](https://github.com/RuiqingDing/OpenCMKG)；三元组 TXT、实体字典、对齐 CSV | 中文实体、症状/疾病/药物关系研究；后续 GraphRAG 候选 | 明确仅学术研究、不得商用；聚合 QAKG、OwnThink、CHIP2021，缺乏逐条临床证据的关系不直接用于建议 |
| Chinese-medical-dialogue-data | [作者仓库](https://github.com/Toyhom/Chinese-medical-dialogue-data)；6 个科别 CSV，792,099 条问答，字段 department/title/question/answer | 对话表达、问法覆盖和清洗研究 | [仓库 LICENSE](https://github.com/Toyhom/Chinese-medical-dialogue-data/blob/master/LICENSE) 为 MIT，但不能据此确认每条上游问答的权利；README 样例本身就有夸大功效描述；低于官方资料优先级 |
| D2hKG | [项目仓库](https://github.com/Cantaloupe-M/D2hKG_Data)；node/edge 与构建脚本，项目列出约 6.3 万实体 | 食品、菜肴、疾病关系结构参考 | 本轮找到具体仓库，但未找到明确 LICENSE；包含爬取网站及传统食养知识，不能把“宜吃/功效”直接视为临床结论 |
| CMExam | [作者仓库](https://github.com/williamliujl/CMExam)；中文医学考试数据 | 医学知识问答评估 | 不是面向百姓的健康科普知识库；考试正确率不能替代 RAG 证据质量验证 |
| HuatuoGPT-II | [作者仓库](https://github.com/FreedomIntelligence/HuatuoGPT-II)、[7B 模型卡](https://huggingface.co/FreedomIntelligence/HuatuoGPT2-7B)；7B/13B/34B 及部分量化权重 | 后续中文医疗回答模型对照实验，可经统一模型服务接入 | 模型权重不是可引用的语料；仍需要中文 RAG。许可证应分别核对模型与对应基座；本轮不替换 Aide 现有 LLM |

## 样例核查的实际发现

Huatuo-Lite 的公开查看器中，id 398799（score=5）和 12147932 的儿童发热回答出现酒精擦拭建议；id 7300413 的牙痛回答出现白酒止痛建议。这里只记录样例问题以说明质量风险，不将这些建议收录为知识。这些记录说明数据集自带 score 不能视为医学复核结果。[查看器](https://huggingface.co/datasets/FreedomIntelligence/Huatuo26M-Lite)

百科子集公开 schema 主要为 questions/answers，未展示逐条 source_url、更新时间、证据等级；仅补一个数据集链接不能冒充医疗原文引用。[百科查看器](https://huggingface.co/datasets/FreedomIntelligence/huatuo_encyclopedia_qa)

本轮没有核实到同时满足“中文完整医疗正文、稳定公开 API、明确允许持久化 RAG”三项条件的通用免费 API。网页和可下载数据集目前更具体可行；不猜测付费厂商 API 的权限或质量。

## 清理与后续约束

- 删除本地 68 篇 MedlinePlus 文档、原始 XML/ZIP、规范化 JSONL、切片导出、staging 副本和影子索引。
- 删除 USDA 下载包、SQLite、节点/关系 CSV 与导入清单。
- 同步研究 collection，移除不再存在的外文文档切片；保留原有中文知识。
- 旧下载/导入入口受中文来源策略拦截；文档模型新增 language，显式英文文档不能进入正式、研究或预览索引。旧中文文档兼容默认 zh，新适配器必须准确声明原文语言。
- 历史评估报告及 Git 提交保留用于追溯，并标记为已停用；历史 Recall@5 不代表当前中文库覆盖率。尚未补齐中文的新主题会出现覆盖缺口，不能通过修改旧题预期掩盖。
- 新候选等用户选择后再做导入。建议先落实一个中文来源，检查正文质量、来源、主题覆盖和实测检索表现，再扩大规模。

清理实测：研究库从 650 切片降为 88 切片，撤回 562 个 MedlinePlus 切片，保留 68 篇中文文档。已检查本地全部 `aide_medical_*` collection，未发现 MPLUS 文档或显式非中文记录。
