# 医疗数据源调查报告（第一轮）

日期：2026-09-24。完整 34 项候选在 [`../registry/datasets.csv`](../registry/datasets.csv)，逐项权利判断在 [`../registry/licenses.csv`](../registry/licenses.csv)。`verified` 只表示核实了来源及基本形态，**不表示数据获准进入回答索引**；可用性以许可证台账的 `answer_eligible` 为准。

## 调查结论

- 第一轮优先接入 MedlinePlus **Health Topic XML 的健康主题摘要**。Aide 已有固定源文件和解析器，本次从原有 18 个主题扩至 68 个；新增 50 个覆盖运动、睡眠、慢病预防、营养和常见症状。官方 [XML 说明](https://medlineplus.gov/xml.html)与[内容使用规则](https://medlineplus.gov/about/using/usingcontent/)分别确认批量获取与摘要可复用。中文词只是检索标签，证据正文仍是英文原文。
- USDA FoodData Central 数据具有[明确 CC0 授权](https://fdc.nal.usda.gov/api-guide/)，但数值数据应在下一阶段作为结构化查询，不做无意义的大量文本切片。
- [DailyMed SPL API](https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm)和[openFDA label 下载](https://open.fda.gov/apis/drug/label/download/)路径明确；内容重用、版本、产品与中国适用性还没审完，因此暂不进入回答索引。
- [PMC Open Access 子集](https://pmc.ncbi.nlm.nih.gov/tools/openftlist/)只能逐篇按许可证判断，不能把 PMC 或 PubMed 的所有论文当成开放全文。
- [OpenCMKG](https://github.com/RuiqingDing/OpenCMKG)明示仅学术研究、不可商用，且是多个上游数据聚合；仅列为离线关系研究候选。[cMedQA2](https://github.com/zhangsheng93/cMedQA2)明示非商业研究用途，且社区问答不能替代医学证据。
- [Huatuo-26M](https://github.com/FreedomIntelligence/Huatuo-26M)仓库声明 Apache-2.0，但聚合内容的上游权利和回答质量须另查；只列离线评估候选。

## 下一轮调查

1. 核对现有国家卫健委及地方来源的逐页使用条件，补齐现有 86 条研究资料的授权与原始版本台账。
2. 对中文高频科普来源逐个确认授权与差量更新方式，择一接入。
3. 对药品说明书、食药关系和本体，调查数据项级许可、地区适用性和原始证据；不让预测关系直接生成医疗结论。

当前没有下载药品、食物相互作用或图谱数据，也没有把这些候选数据投入在线回答。
