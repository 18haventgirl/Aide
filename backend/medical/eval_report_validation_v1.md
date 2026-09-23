# 医疗 RAG validation v1

题集：`eval_cases_validation_v1.json`，SHA256：`88e53be42bcb08b45cefcb606455d79d471b4c463e52d2e60d3bf40fd6c64e7a`。

该题集在创建后先运行一次，再检查失败项。首次结果发现急症表达和临床决策范围规则的通用缺口；修复后题集保持冻结。由于这些失败项已经用于修复，它现在属于锁定回归集，不再宣称是完全独立的盲测集。真正独立的评测仍需由未参与实现的人提供。

| 指标 | 首次运行 | 通用规则修复后 |
| --- | ---: | ---: |
| Recall@1 | 0.933 | 0.933 |
| Recall@5 | 1.000 | 1.000 |
| MRR | 0.956 | 0.956 |
| nDCG@5 | 0.967 | 0.967 |
| 无答案/临床决策拒绝率 | 0.500 | 1.000 |
| 急症表达识别率 | 0.000 | 1.000 |
| 追问 Recall@5 | 1.000 | 1.000 |

修复内容：

- 急症判断不再依赖“突然”必须出现在症状前面的固定语序。
- 增加胸痛合并出汗或呼吸异常、卒中组合信号、严重呼吸困难、自伤准备及爆发性严重头痛的表达。
- 儿童具体剂量、多药合用剂量、主动改药频次和图片诊断进入 `clinical_decision` 范围，不再把普通检索结果作为个体方案。
- `medical_search` 把 `urgency` 和 `scope` 明确交给 Medical Agent，最终回答仍由统一 LLM 生成。

复现命令：

```powershell
.\.venv\python.exe -m medical.evaluate --cases medical/eval_cases_validation_v1.json --k 5
```
