# 阶段3第二批中文来源与封存工具

记录：2026-10-29。实现提交`953ec41`。本轮完成来源扩展、题集预检和封存工具；未进行真实BGE检索或LLM生成验收，未切换运行索引。

## 实际交付

| 项目 | 上一隔离快照 | 本轮隔离快照 |
| --- | ---: | ---: |
| 中文文档 | 73 | 75 |
| 不同来源URL | 8 | 10 |
| 逐段原文映射 | 69 | 72 |
| 待补映射 | 4 | 3 |
| 19主题的局部覆盖/无专门来源 | 13 / 6 | 15 / 4 |

新增北京市卫健委的头晕、便秘选段；补齐福建头痛旧资料的20段正文、2个原标题映射。仍缺`BJ-DIARRHEA-20210406`、`NHC-FLU-CARE-20250117`、`NHC-THROAT-20240821`的sidecar。头晕只补症状描述、病因复杂和规范就诊，不含完整急症警示；便秘只是行为习惯和部分就医变化，未选统一饮水公式、特定食疗功效、具体运动处方、孕期用药或泻药类别绝对化说法。

原文选择、全部遗漏理由、来源链接和许可限制见`source-research-20261028.md`。来源核对不等于临床审核或医学覆盖完整。

## 存储和版本

- 原始HTML与派生段落：`D:\Workplace\Aide\medical-rag-data\raw\<来源ID>\<采集日期>\`，两种资产分别保存hash。
- 选择配方：`medical-rag-data/registry/chinese_official_batch_20261028.json`，入Git。采集10月27日、选段10月28日、构建10月29日，保留实际日期。
- 导入包：`medical-rag-data/staging/official-zh-bundles/2026-10-29/`，包含两篇document+origin和头痛origin-only更新。
- 新快照：`medical-rag-data/datasets/official-zh-v3/2026-10-29/`，内含`corpus/`、`origins/`和`snapshot_manifest.json`；旧v2不覆盖。
- 审计归档：`backend/medical/evaluation/results/stage3_source_snapshot_v2.json`、`stage3_coverage_inventory_v3.json`、`source_batch_preflight_v1.json`。原料全文和快照留在Git忽略目录。

新corpus SHA256：`b48452cc0aa478b6b82f917d6f6d428441e32d7e822f46d78c35420a0ce04e82`；origins SHA256：`0c8528cbe81c10fef808e2291d17d2616bd7e653ef631d111e8ca0ed1585249e`。

builder支持多篇新增和只补映射。文档变更必须加version，未变文件沿用原始字节；父快照manifest/corpus/origins递归核验，原HTML/PDF与派生文本独立校验。验收后才原子写入`complete=true`，失败目录保持未完成。**这只是离线快照完成标志，不等于在线索引原子发布已经实现。**

历史72篇文件集合hash仍为`0a6eb5e5094cf63c4db0c64f10f880d40d7527be96a4a8472cdd52730caf7632`；新快照内71份旧文件字节相同，腹痛沿用上轮v2边界修正。

## 题目与验收

新增12道已暴露开发题：头痛4、头晕3、便秘5；10单问、2追问，15个原文范围、1个适用条件。旧12题作为回归，合并suite共24题、29范围、3条件、5主题，全部gold通过逐字来源检查，ID和规范问题无重复。

全部属于开发/回归；**新独立验证题仍为0**，120开发/80验证/40流程未完成。新题没有负例，不能用于拒绝率评价。

题集封存工具提供seal/audit、文件字节及规范JSON双哈希、题目家族/模板/相似表达与历史曝光检查、来源快照及代码绑定、只读审计；详见`evaluation-partition-contract.md`。本轮没有伪造正式验证seal，实验入口尚未强制消费seal。

76项来源、快照、划分和实验回归测试联合通过，日志`logs/stage3-extension-tests-20261029.log`；独立复核题集20项通过（属于76项的子集，不相加）。真实原料构建和24题严格预检也通过。

模型前检查可用内存1388.5MiB，低于1536MiB门槛；用户选择“这轮先完成其余工作”。未启动BGE/reranker，未调用生成API，没有本批新的召回率/耗时结果。预检报告明确`run_kind=source_preflight_not_retrieval`、`retrieval_executed=false`，不能把标签通过当检索命中。

## 发现与处理

1. 新版快照删除parent字段后原审计可能放行。已强制schema2的父链/新增ID/origin更新声明，拒绝未知版本与不兼容声明，增加回归测试。这是完整性防错，不是抵抗重写全部文件的签名系统。
2. 头痛旧source hash实际上是摘录hash。保留文档并明示类型，独立绑定归档HTML；不伪称本次重新取得HTTP响应。
3. 非追问题的history在真实评测中不参与查询，原判重却会使用它。已按实际合同归一化，并拒绝新封存题使用这种无效前文掩盖重复。
4. 两个NHC候选直接请求412，浏览器虽曾可见其中一篇但未完成保存；未计入可用来源。
5. 官方资料也须筛选适用范围。头晕警示段与诊断模式混合，本次整段排除，缺口保留；便秘“十种情况”实际选六项，标题/usage明示为原文选段。

## 后续及复现

先补三篇来源映射、成人发热/短期咳嗽及头晕急症原文，扩展开发题、困难负例和隔离验证家族。内存允许且恢复模型测试时运行24题首次hybrid/rerank对照，分别记录候选池、实际模型输入与最终证据损失。正式调参前让实验入口强制消费验证seal，然后进入排序/依据充分性校准。阶段2发布门槛未过，阶段3未全验收。

快照重建要求固定hash的原料：用`medical.capture_official_batch --recipe <配方> --output <全新staging目录>`重放，调用`capture_headache_origin.build_origin`生成头痛映射，再执行`medical.build_source_snapshot --parent <v2目录> --output <全新datasets目录> --bundle <头晕包> --bundle <便秘包> --origin <头痛映射> --as-of 2026-10-29`。禁止覆盖现有快照。新环境原料恢复仍属阶段6待验。

待运行命令（在backend，释放内存后，选择不存在的结果文件）：

```powershell
.\.venv\python.exe -m medical.experiment --suite medical\evaluation\source_batch_suite_v1.json --corpus ..\medical-rag-data\datasets\official-zh-v3\2026-10-29\corpus --source-snapshot ..\medical-rag-data\datasets\official-zh-v3\2026-10-29 --metric-contract source-evidence-v1 --profiles hybrid rerank --input-policy query_first_v1 --chunk-strategy token-v1 --child-tokens 180 --rerank-max-length 256 --output data\evaluation_reports\source_batch_first_20261029_v1.json
```
