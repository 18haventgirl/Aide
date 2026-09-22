# 医疗健康 RAG 开放数据源调研

更新日期：2026-09-22

## 目标

为面向普通用户的中文健康助手选择可追溯、可更新、许可清晰的数据源。首版范围是健康科普、常见症状的就医引导、用药安全和营养知识，不把研究性预测或网络问答直接当成临床事实。

## 结论

现有资料清单的分类思路正确，但不同数据源不能混在一个可信层级中：

1. 官方患者教育、指南和药品标签可以作为回答依据。
2. 医学本体只用于名称归一、同义词扩展和检索增强，不能独立回答临床问题。
3. 论文、问答语料和自动抽取关系适合补充检索或评测，需要保留证据等级。
4. 网页抓取图谱、传统“食物相克”和模型预测关系只能作为待核验线索。

不存在一张可信、通用的“食物相克表”。应分别处理食物与药物相互作用、过敏、食物不耐受、疾病相关饮食限制和食品安全。民俗“相克”不得作为确定性医疗建议。

## 第一批建议接入

| 数据源 | 主要用途 | 格式 | 许可与限制 | 接入建议 |
| --- | --- | --- | --- | --- |
| 国家卫健委健康科普与辟谣内容 | 中文健康科普、就医提示、营养和合理用药 | HTML/PDF | 官方页面，逐页保存来源和发布时间；批量再利用条款需单独核对 | 最高优先，建立白名单采集器和人工审核状态 |
| NHS Website Content API | 症状、疾病、药物、检查及患者教育 | JSON API | 多数内容可按其复用条款使用，存在排除内容和刷新频率要求 | 适合补足结构化患者教育；中文翻译须标记为派生内容 |
| MedlinePlus Health Topics | 面向公众的疾病和健康主题 | XML/API | NLM 内容中同时存在公有领域和受版权保护内容，需按内容类型核对 | 可用于英文原文检索和主题映射，不应默认整站内容都可自由复制 |
| DailyMed / openFDA Drug Label | 适应症、禁忌、警告、不良反应、相互作用 | SPL XML、ZIP、JSON API | 美国官方数据；openFDA 一般为公有领域/CC0，个别字段可能例外 | 药物安全层的核心来源，但要明确“美国标签”，不能替代中国说明书 |
| USDA FoodData Central | 食物营养成分和每 100g 含量 | CSV、JSON、API | 公有领域，CC0 1.0 | 用结构化数据库查询，不需要把数值表全部向量化 |
| Mondo | 疾病 ID、同义词和跨库映射 | OBO、OWL、JSON | CC BY 4.0 | 用于疾病实体归一和查询扩展 |
| HPO | 症状和表型标准词汇 | OBO、OWL | 需遵循项目许可和引用要求 | 用于症状归一、同义词和上下位词扩展 |
| RxNorm | 药物成分、剂型、品牌映射 | RRF、API | 完整发布需遵守 NLM/UMLS 条款；部分 Current Prescribable Content 无需许可 | 用于英文药物归一；另建中文商品名和通用名映射 |
| MeSH | 医学主题词和层级 | XML、RDF | 遵守 NLM 使用条款 | 用于主题分类和跨语言检索辅助 |

## 第二批研究性数据

| 数据源 | 可以做什么 | 主要风险 | 建议 |
| --- | --- | --- | --- |
| PMC Open Access Subset | 查找开放全文证据、综述和临床研究 | 每篇文章许可不同；只能通过官方允许的批量接口获取；专业论文不适合直接面向普通用户 | 只选主题相关、许可兼容的综述和指南；保留文章级许可 |
| FooDrugs | 食物与药物潜在相互作用研究、关系候选生成 | 数据量约 3.9GB；大量关系来自文本挖掘或分子推断，属于“潜在相互作用” | 用于候选发现，最终回答需回链药品标签或原始论文 |
| DFI Corpus | 训练或评估食物药物关系抽取 | 是标注语料，不是临床建议库 | 用于 NER、关系抽取和离线评测 |
| KG-DFI | 研究食物药物图谱和关系预测 | 模型预测不能视作已证实相互作用 | 仅作为研究模块；预测边默认不进入回答证据 |
| MedQuAD | 医疗问答检索基线和评测 | 部分 MedlinePlus 子集因版权移除了答案 | 适合构建评测集和问题改写，不优先作为主知识源 |
| Huatuo-26M / Huatuo-Lite | 中文问法、召回评测、问题扩展 | 虽然仓库声明 Apache 2.0，但原始内容包含网络百科和咨询数据，真实性、时效性和底层内容权利需要逐项核对 | 首选 Lite 做实验；答案不能直接成为高可信依据 |

## 中文知识图谱的使用边界

### OpenCMKG

- 约 60,696 个实体、354,755 条三元组，包含疾病、症状、药物和食物关系。
- 仓库明确限定“仅用于学术研究，不得用于商用”。
- 数据聚合自多个图谱和比赛数据，适合本机研究、实体词典和召回实验。
- 不进入未来商业版本的生产知识库。

### D2hKG

- 约 63,745 个实体，含疾病、药物、食材、菜肴和 215 条“相克”关系。
- 数据包含网站抓取内容，仓库未发现明确许可证。
- “蜂蜜—相克—韭菜”等关系应标记为 `traditional_claim`，不得当作循证结论。
- 仅用于研究传统饮食说法及构造辟谣问题集。

### 其他中文食物数据

- GitHub 上存在从《中国食物成分表》截图转录的仓库，但原书内容的再分发权不清晰，不建议纳入项目。
- 登录后爬取第三方营养网站的数据同样存在授权问题，不建议采用。
- 中国食物本地化可先以 USDA 数据为营养基准，自建中文别名映射；之后再寻找有明确授权的中国食物成分来源。

## 食物相关知识模型

不要建立单一 `food_conflict` 表。建议使用以下关系：

```text
drug_food_interaction       药物与食物/营养素相互作用
allergen_contains           食物含过敏原
intolerance_related         乳糖、麸质等不耐受关系
disease_diet_caution        特定疾病的饮食注意事项
food_safety_risk            生食、污染、储存等风险
traditional_claim           民俗或传统说法，尚未得到可靠临床证据支持
```

每条关系至少包含：

```json
{
  "subject": "warfarin",
  "relation": "drug_food_interaction",
  "object": "vitamin K",
  "effect": "may reduce anticoagulant effect",
  "recommendation": "maintain a consistent intake",
  "evidence_type": "official_drug_label",
  "evidence_level": "A",
  "assertion_status": "verified",
  "jurisdiction": "US",
  "source_url": "...",
  "source_updated_at": "...",
  "license": "...",
  "review_status": "machine_checked"
}
```

## 证据等级

| 等级 | 数据类型 | 回答方式 |
| --- | --- | --- |
| A | 官方指南、官方患者教育、药品标签 | 可直接作为 RAG 核心证据，保留适用地区和日期 |
| B | 系统综述、临床指南、可靠医学机构内容 | 可作为补充证据，优先给出来源 |
| C | 单项研究、观察研究、病例报告 | 使用谨慎措辞，不概括成普遍结论 |
| D | 知识图谱聚合、自动抽取、问答语料 | 只做召回候选，需由 A/B/C 级来源复核 |
| E | 传统说法、网页抓取、模型预测 | 不作为医疗结论，可用于辟谣或待核验队列 |

## 适合 Aide 的落地顺序

1. 扩充国家卫健委官方中文科普，覆盖发热、腹痛、头痛、咳嗽、腹泻、胸痛、过敏等常见问题。
2. 增加 NHS Content API 或 MedlinePlus 的患者教育内容，保留英文原文和机器翻译版本的对应关系。
3. 增加 openFDA/DailyMed 药品警告和相互作用结构化解析，首批只做常见通用药。
4. 将 FoodData Central 作为单独的营养 SQLite 表，通过工具查询，而不是全部存入 Chroma。
5. 用 Mondo、HPO、RxNorm 和 MeSH 建立实体别名表，支持“布洛芬/ibuprofen”等跨语言归一。
6. FooDrugs、DFI Corpus、OpenCMKG 和 Huatuo-Lite进入实验区，不能和已核对生产语料混用。
7. 建立固定问题集，分别评估召回率、证据等级命中率、引用正确率和危险建议率。

## 已核验链接

- 国家卫健委健康科普辟谣平台：https://www.nhc.gov.cn/kppypt/index.shtml
- NHS Website Content API：https://digital.nhs.uk/developer/api-catalogue/nhs-website-content
- MedlinePlus Developers：https://medlineplus.gov/about/developers/
- DailyMed SPL：https://dailymed.nlm.nih.gov/dailymed/spl-resources.cfm
- openFDA：https://open.fda.gov/
- FoodData Central：https://fdc.nal.usda.gov/download-datasets/
- PMC Open Access Subset：https://pmc.ncbi.nlm.nih.gov/tools/openftlist/
- FooDrugs：https://zenodo.org/records/8192515
- DFI Corpus：https://github.com/ccadd-snu/corpus-for-DFI-extraction
- KG-DFI：https://github.com/bmil-jnu/KG-DFI
- MedQuAD：https://github.com/abachaa/MedQuAD
- Huatuo-26M：https://github.com/FreedomIntelligence/Huatuo-26M
- OpenCMKG：https://github.com/RuiqingDing/OpenCMKG
- D2hKG：https://github.com/Cantaloupe-M/D2hKG_Data
- Mondo：https://github.com/monarch-initiative/mondo
- HPO：https://github.com/obophenotype/human-phenotype-ontology
- RxNorm：https://www.nlm.nih.gov/research/umls/rxnorm/docs/rxnormfiles.html
- Open Food Facts：https://openfoodfacts.github.io/openfoodfacts-server/api/

