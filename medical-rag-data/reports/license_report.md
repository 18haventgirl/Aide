# 数据权利与准入记录（第一轮）

日期：2026-09-24。此文件记录实施状态，不代替原始使用条款。逐项字段和原文链接见 [`../registry/licenses.csv`](../registry/licenses.csv)。

## 已确认的边界

| 数据集 | 本轮判定 | 理由 |
| --- | --- | --- |
| MedlinePlus 健康主题摘要 | `OPEN`，允许本机研究问答接入 | [NLM 使用说明](https://medlineplus.gov/about/using/usingcontent/)将 health topic page summaries 列为公有领域内容，并要求注明来源。只处理官方 XML 的 `full-summary`。 |
| MedlinePlus A.D.A.M. 百科与 AHFS 药物专论 | `RESTRICTED`，不导入 | 同一使用说明明确列为第三方受版权保护内容。 |
| USDA FoodData Central | `OPEN`，后续结构化试点 | [官方 API 指南](https://fdc.nal.usda.gov/api-guide/)说明数据采用 CC0，并请求标注 USDA 来源。 |
| OpenCMKG | `RESEARCH_ONLY`，不作为回答证据 | [仓库 README](https://github.com/RuiqingDing/OpenCMKG)写明仅学术研究、不得商用；上游权利仍需核查。 |
| cMedQA2 | `NON_COMMERCIAL`，不作为回答证据 | [仓库 README](https://github.com/zhangsheng93/cMedQA2)写明非商业研究用途；社区问答还需独立质量控制。 |
| RxNorm 完整数据 / UMLS | `REGISTRATION_REQUIRED`，暂不导入 | [NLM RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/overview.html)说明完整发布须 UTS/UMLS 许可，且第三方词表可能另有限制。 |

## 暂不放行

PMC OA 逐篇许可证、DailyMed/openFDA 内容、现有国家卫健委/地方网页、HPO 注释、FooDrugs、KG-DFI、DFI Corpus、D2hKG 等保留为 `UNKNOWN` 或其他受限状态。能访问 API、GitHub 仓库或论文页面，不自动取得全文复制、翻译、再分发、RAG 展示或模型训练权利。许可变化按数据集及记录版本重新核查。

`backend/medical/data_registry.py` 在新来源导入前执行 fail-closed 检查：只有 `OPEN`、`rag_use=yes`、`answer_eligible=yes` 同时成立才允许进入新增回答证据流程。现有 86 条研究资料尚待来源级审计，因此本轮没有改写旧资料状态，也没有声明它们适合公众发布。
