# 中文资料 v4 与首批本地留出题

2026-11-04，隔离构建通过原料和父版本审计。实现提交 `4df4e0a`。本批快照位于 `medical-rag-data/datasets/official-zh-v4/2026-11-04/`，运行应用仍使用原有索引配置。

| 指标 | 10月29日 | 11月4日 |
| --- | ---: | ---: |
| 中文资料 | 75 | 77 |
| 不同来源链接 | 10 | 12 |
| 有逐段来源映射的资料 | 72 | 77 |
| 待补映射 | 3 | 0 |
| 严格来源开发及回归题 | 24 | 50 |
| 已封存的本地留出题 | 0 | 12 |

新增潜江市卫健委的感染后咳嗽节选和深圳市医疗卫生专业服务中心的家用测温节选。前者保留通常病程与四项就医提示，后者保留影响额温读数的因素、复测和持续发热就医提醒。19个规划主题里15个有部分覆盖，过敏、腰背不适、皮肤不适和疲劳仍缺专门来源。77篇中有66篇来自同一份健康素养释义PDF。选段和来源见 [采集记录](respiratory-sources-20261102.md)。

腹泻资料与原网页逐字匹配，沿用旧版。流感和咽喉资料分别升级为v2，引用实际取得的同场官方发布会实录。流感摘录按实录校正一字，咽喉摘录的两句分开绑定到实际所在段。以上三篇均属于来源修复。全文原料、派生文本和规范资料分别保存在本机，Git保存配方、指纹和审计记录。逐字映射核验的对象是保存的来源文本，其中PDF按已声明的提取规则规范化。临床复核和公开再分发许可仍按原计划另行处理。[来源修复记录](legacy-symptom-sources-20261102.md)

语料指纹为 `ed903e734423da9e83dbd5d4c1a408cf348ede7273011545039e07b6218bfd43`，来源映射指纹为 `472f2bc4dc3cd87728ebb133aecd63283aca9603879f878c43fdf2e10d10fbfb`。旧72篇基线中69份文件在v4字节一致，三个升版文档为腹痛、流感和咽喉。构建时工作树另有运行脚本改动，全局 `tracked_changes` 据实为 true。报告记录了本次使用的实现指纹。[快照审计](../backend/medical/evaluation/results/stage3_source_snapshot_v3.json) · [主题清单](../backend/medical/evaluation/results/stage3_coverage_inventory_v4.json)

## 开发与验证

在旧24题基础上新增10道有依据问题和16道缺乏所问事实的问题。50题共27道单问、7道追问、16道无依据题，42个证据范围及12个适用条件通过原文核对。新混合题集与原274题对比，ID和规范化输入均无重复。按整篇文档用BM25检查负例，有9/16题的指定干扰文档排进前三。这衡量题目和干扰文章的词语重合程度。线上证据块的召回、重排表现和负例拒绝率仍待模型实验。[预检报告](../backend/medical/evaluation/results/source_mixed_preflight_v1.json)

首批12道留出题由未查看开发题或模型结果的独立作者按原文编写。包含7道单问、3道追问、2道无依据题。封存前对照了50道开发及回归题，并检查10份历史曝光文件共349条记录、342个不同的规范化输入。已实现的ID、家族、模板、规范输入和近似表达检查均通过。旧华佗候选题保留原始文件哈希，以 `expected_ids` 格式参加历史曝光检查。划分检查依赖现有标签和相似度阈值，语义层面的审查、临床评价和完整80题留出集仍待建设。

本机封存文件为 `backend/medical/evaluation/local_holdouts/partition_data_seal_20261104_v1.json`，SHA256 为 `d72c6700dd2fd30c0590d45dab1f25a48fab75d62fda70ea58bd00cdd76ff3c9`。题面和本机封存清单留在忽略目录，仓库仅归档核验所需的摘要。保存本地原料和留出目录是恢复这次封存的前提。当前封存固定了资料与题目。待开发集完成参数选择、首次实验门槛确定后，再创建引用同一批题及语料的运行登记版本。真实验证运行次数为0。[封存回执](../backend/medical/evaluation/results/holdout_seal_receipt_v1.json)

正式实验在模型加载前核对封存SHA、完整题组、来源、实现指纹及登记参数。复核还发现旧 `medical.evaluate --cases` 可以直接读取留出题并进入模型初始化。该入口和公共suite加载器现均有封存检查。112项相关回归测试联合通过，含合成数据的正常和拒绝路径。日志在 `logs/stage3-source-v4-final-20261104.log`。[封存合同与命令](evaluation-partition-contract.md)

## 下一次实验

本次检查可用内存476.6 MiB，真实BGE实验门槛为1536 MiB。尚无v4向量召回、重排或最终回答成绩。可用内存恢复后，先对开发题运行以下命令，保存首次结果。根据模型输入与最终证据中的实际得失决定下一轮调整。12道留出题继续封存。

```powershell
# 在 backend 目录执行，输出文件必须尚未存在
.\.venv\python.exe -m medical.experiment --suite medical/evaluation/source_mixed_suite_v1.json --source-snapshot ../medical-rag-data/datasets/official-zh-v4/2026-11-04 --corpus ../medical-rag-data/datasets/official-zh-v4/2026-11-04/corpus --metric-contract source-evidence-v1 --profiles hybrid rerank --input-policy query_first_v1 --chunk-strategy token-v1 --child-tokens 180 --rerank-max-length 256 --output data/evaluation_reports/source_mixed_development_v4_first.json
```
