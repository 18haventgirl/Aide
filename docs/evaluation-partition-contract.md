# 开发题与独立验证题的封存合同

更新：2026-10-29。对应 `rag-engineering-execution-plan.md` 阶段3.3～3.6。实现为 `backend/medical/evaluation/partitioning.py` 和 `partition_manifest.py`。

## 当前交付与边界

已实现题集划分检查、封存清单生成和只读复核工具。本轮两组合同测试共20项通过。测试使用合成题与隔离来源快照，没有运行检索、生成模型或外部评审。

**工具完成不等于独立验证集完成。** 已有旧回归题、12道 source pilot 开发题以及本轮正在集成的开发题都已暴露，不能通过改名或改 `exposed_for_changes` 变为独立验证题。计划中的120开发题、80独立验证题、40个可执行流程仍按主方案另行建设；本文件不宣布这些数量已达成。

封存状态固定为 `sealed_local_not_external_blind`。这是本地完整性和机械重复检查，不能证明语义独立、临床正确、公开使用许可或真正的外部盲测。

## 检查哪些内容

| 内容 | 实际检查 |
| --- | --- |
| 划分 | 必须同时提供非空 development、validation；ID不能重复，题目必须声明正确split、topic、family_id、template_id和布尔曝光状态 |
| 题目关系 | 不允许跨开发/验证家族或模板复用；规范化问题及有效前文重复会拒绝；跨组字符n-gram Jaccard达到阈值会拒绝并报告 |
| 前文 | 与当前评测合同一致，仅followup使用history；新封存题若不是followup却带非空history，直接拒绝，防止用无效前文掩盖相同输入 |
| 历史曝光 | 必须显式传入至少一个历史题文件；验证题与这些文件检查ID、规范化输入、家族、模板和近似表达。换ID、换家族名不能掩盖相同问题 |
| 正例证据 | supported/followup的每个目标doc_id都必须有版本、body哈希和非空原文范围；范围必须落在已核验source_text/source_heading中，编辑标题、无映射资料不能作为gold |
| 非正例 | unanswerable/urgent必须说明 `no_evidence_reason`；所有新封存题必须说明authorship，负面文档ID也必须在所绑定语料中存在 |
| 来源绑定 | 审计整个隔离source snapshot，核验原料、sidecar及继承关系；保存快照清单文件哈希、corpus哈希、origins哈希和覆盖数量 |
| 可选逐题绑定 | 题目如提供source_binding，会进一步核对来源定位、版本和规范文档哈希；即使未提供，正例范围与整份语料的绑定仍是强制项 |
| 代码绑定 | 保存检查实现的逐文件哈希、Git提交、tracked changes及未跟踪的绑定文件列表；只修改文档导致Git提交变化可以复核，检查代码字节变化则需新封存版本 |

近似检查阈值默认0.85，只接受0.5～1之间的有限数值。它是需要解释的机械阈值，不是医学语义判定；不得为让验证题通过而逐题放宽阈值。共享同一检索语料是允许的，并在报告中列出两组共享的来源ID。

历史曝光清单不是自动扫描整个仓库得到的。操作者必须纳入所有已用于开发、排障、调参或查看结果的题集；工具只能保证传入清单的绑定和重复核验，无法证明没有遗漏历史曝光。

## 文件与复核规则

封存清单同时保存每个题文件的原始字节SHA256、规范JSON哈希、题数和相对路径。两个哈希职责不同：规范哈希用于描述相同JSON内容，字节哈希使增加换行等文件改动也显式触发重新封存。

`seal`只允许创建新清单，不覆盖已有文件。`audit`重新读取题目、历史曝光记录、来源快照和实现代码，重跑检查并对比保存的结果；不修改这些文件，不调用LLM或重建索引。失败返回非零退出码，常见合同或文件错误会输出包含 `valid:false` 的JSON。

题文件和清单必须在data-root内；来源快照在snapshot-root内，原料受raw-root及来源审计规则限制。清单中的路径必须为相对路径，禁止越界。清单不是数字签名或访问权限系统：拥有文件写权限的人仍可修改整套材料，正式实验应另外记录清单SHA256并保留版本历史。

## 使用方法

以下从 `D:\Workplace\Aide\backend` 执行，是未来真实开发/验证题文件准备完成后的命令模板。`development_v1.json`、`validation_v1.json`、`exposed_history_v1.json` 是示例文件名，**本工具没有替用户生成这些题目**。调用前替换为实际已核对文件；多个历史文件逐个追加 `--exposed`。快照示例使用已存在的2026-10-17隔离版本，选用其他快照时必须同步替换。

```powershell
.\.venv\python.exe -m medical.evaluation.partition_manifest seal `
  --development D:\Workplace\Aide\backend\medical\evaluation\development_v1.json `
  --validation D:\Workplace\Aide\backend\medical\evaluation\validation_v1.json `
  --exposed D:\Workplace\Aide\backend\medical\evaluation\exposed_history_v1.json `
  --snapshot D:\Workplace\Aide\medical-rag-data\datasets\official-zh-v2\2026-10-17 `
  --manifest D:\Workplace\Aide\backend\medical\evaluation\partitions_v1.json

.\.venv\python.exe -m medical.evaluation.partition_manifest audit `
  --manifest D:\Workplace\Aide\backend\medical\evaluation\partitions_v1.json
```

默认data-root是 `D:\Workplace\Aide\backend\medical`，snapshot-root是 `D:\Workplace\Aide\medical-rag-data\datasets`，raw-root是 `D:\Workplace\Aide\medical-rag-data\raw`。使用另外的隔离测试目录时，seal和audit都需传相同的三个root参数。正式封存应先提交绑定代码，避免生成无法仅由所记Git提交恢复的未提交实现；工具会如实记录脏工作区和未跟踪实现，而不是隐藏它们。

## 下一步接入

1. 按来源覆盖和题目家族编写真正的新开发/验证题，负例明确缺少何种依据；不要复用已暴露回归题充数。
2. 汇总历史曝光文件并做语义层面的划分检查，再封存验证题和首次实验门槛。
3. 将封存清单及其SHA256纳入实验启动前的强制检查。当前 `experiment.py` 尚未强制消费这个封存工具的清单，不能声称仅使用现有实验命令就会自动执行全套划分审计。
4. 验证结果被用于修复或调参后，将相关题转为回归并补充新验证题，保留旧清单与首次结果。

测试命令：

```powershell
$env:TMP='D:\Workplace\Aide\logs\evaluation-test-tmp'
$env:TEMP=$env:TMP
.\.venv\python.exe -m unittest tests.test_partition_manifest tests.test_evaluation_partitioning -v
```

2026-10-29实际结果：20项通过，3.563秒。包括封存/只读复核往返、字节变化、来源及曝光文件变化、编辑标题和缺失来源gold拒绝、改ID复用旧题拒绝、代码变化、路径越界、无效合同和有效前文规则。这些是软件合同测试，不是20次真实医疗问答验收。
