# 可复现医疗检索实验基础

日期：2026-10-06，对应主方案 M1a。

## 契约与运行

`backend/medical/evaluation/suite_v1.json` 锁定现有154题：111开发、33历史回归、10中文新增主题。每组明确用途，规范JSON内容SHA固定标签而兼容LF/CRLF；清单原文件哈希另进报告。这里没有新建240题，也没有外部盲测。

```powershell
# 在 backend 目录运行；不调用生成模型，不修改线上索引
.\.venv\python.exe -m medical.experiment --suite medical/evaluation/suite_v1.json --metric-contract legacy-doc-v3 --group legacy-regression --group chinese-symptoms --output data/evaluation_reports/retrieval_legacy_contract_reproduction.json
.\.venv\python.exe -m unittest tests.test_evaluation_experiment tests.test_pilot_retrieval
```

不传 group 会运行三组。每次进程在独立内存 Chroma 对当前中文 corpus 建库，明确截至2026-10-06的资格；不会打开应用 persistent Chroma 或用户数据库。来源快照、模型/权重、索引策略、代码commit/dirty及检索实现哈希、参数/环境、初始化和逐题耗时进入报告。失败保留 incomplete 与异常类型，不能冒充完整成功。

报告放在本机 ignored目录 `backend/data/evaluation_reports/`。使用真BGE+真重排，CPU2线程，embedding batch4，reranker batch1/max_length256。先检查可用内存1536MiB，重排加载前再次检查；该配置面向本机实验，不等于线上服务batch设置。

## 模式与指标

- keyword：全库jieba/BM25正分候选、每文档最多2块，不进行语义拒绝。它是词法基线，没有假装与线上所有门槛相同。
- dense：BGE候选、相同日期/权限资格和距离过滤，禁用BM25/重排。
- hybrid：BGE+BM25、既有加权RRF与候选池；不重排。
- rerank：相同混合候选池，再真实BGE交叉编码器重排；每题记录 applied/fallback/disabled。

Recall按相关文档命中数/全部标注相关文档数计算；MRR在TopK截断，版本改为 `multi_relevant_v3_mrr_at_k`。保留mrr字段作兼容，但其新定义已改变。nDCG按多正例计算。无正例指标返回null，不宣称100%。拒绝率仅表示检索不给候选，不表示LLM不回答。

旧33题含已撤下英文ID：保留原标签，同时报告8个不可用预期ID；低召回部分来自当前覆盖缺口。新主题不允许未知/不合资格预期ID静默通过。冻结组被用于调参后必须标回归，不能继续称未见测试。

## 第一轮实际对照

33题历史回归，未改标签：

| 模式 | Recall@5 | MRR@5 | nDCG@5 | 无答案拒绝 |
| --- | ---: | ---: | ---: | ---: |
| keyword | .533 | .522 | .490 | 5/8 |
| dense | .544 | .622 | .554 | 7/8 |
| hybrid | .644 | .678 | .617 | 7/8 |
| rerank | .644 | .689 | .633 | 8/8 |

10题中文新增主题：各模式Recall@5均1.0；keyword MRR=.883，其他模式1.0。题集太小且较直接，不支持“重排全面提高召回”的结论。

初次实验中keyword/dense/hybrid历史集P95约1.9/40/40.6ms，batch1重排约4456ms；这不是HTTP端到端，也不能直接与旧batch8线上热查询对比。重排本轮改善排序和一个无答案样例，付出明显CPU延迟；后续应以更多困难样例比较批次、候选数量及必要时的按需重排，不预先承诺效果。

首轮72篇、95块建库与embedding加载约39.6秒，重排单独加载约2.4秒，进程峰值约1116MiB。模型加载与首查单列；温模型结果不能替代冷启动体验。最终版runner会再保存完整版本报告，具体耗时以该报告为准。

本轮不修改线上检索门槛；没有调用LLM judge或验证医学事实正确性。下一步M1b新增独立表达与答案要点，M1c做答案级评分和明确模型预算。
