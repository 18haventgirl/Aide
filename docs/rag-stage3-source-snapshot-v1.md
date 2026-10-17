# 阶段3首个来源快照：实际结果与边界

日期：2026-10-17。构建/复核代码`2968b5c`，当时tracked_changes=false。

## 已完成的数据工作

| 项目 | 实际结果 |
| --- | --- |
| 独立目录 | `medical-rag-data/datasets/official-zh-v2/2026-10-17` |
| 规范文档 / 不同来源URL | 73 / 8 |
| 新增 | 1篇成人睡眠资料，来自全国爱卫办中文官方文章 |
| 修正 | 腹痛资料v1→v2，移除不在原声明节选范围内的第三节200字符 |
| 原文坐标验证 | 69篇通过；4篇待补原页捕获 |
| 来源类型 | 原文正文87段、原文标题7段；68个编辑标题不算逐字医学来源 |
| 历史文件保护 | 71份直接复制的规范JSON字节不变；腹痛新版本仅存在于新快照，旧72篇目录未修改 |
| 运行索引 | 未切换；仍为既有72篇/95块配置 |

语料规范JSON hash：`2539d5b0dfe456ed90655a366ab7582841c52b8d66b2d3ff7393cf5a964fdf49`。

来源sidecar集合hash：`d8c1642f94f7a8059573ddbb359e660472a4c0e6254bfb86c28bdfa2d2191add`。

可提交的逐文档核验摘要：`backend/medical/evaluation/results/stage3_source_snapshot_v1.json`。原料、全文新快照和sidecar保留D盘忽略目录，没有把原始全文上传Git。睡眠捕获是浏览器可见段落文本，PDF/HTML旧原料的派生提取明确记录处理方法，同时校验原始资产hash；这些不冒充逐字原始HTTP响应。

待补来源映射4篇：`BJ-DIARRHEA-20210406`、`FJ-HEADACHE-20260626`、`NHC-FLU-CARE-20250117`、`NHC-THROAT-20240821`。不存在sidecar时返回unmapped，不默认算成来源已验证。后续搜索旧目录找到了头痛完整HTML（`medical-rag-data/datasets/chinese-official/2026-09-28/raw/fj-headache.html`），SHA256与既有定位记录一致，20条正文行均能唯一匹配原页提取文本。此快照仍未为它建立sidecar，不能提前把69改为70；下一版本可复用该原料，不必重复下载。

## 来源合同接入评测

新增可选`source-evidence-v1`，要求`--source-snapshot`与corpus匹配，先运行快照核验，再校验每个正例都有逐字原文范围。编辑标题、缺少原料/来源清单、过期版本、被修改原料或sidecar均拒绝进入模型评测。题集声明此合同时，不能使用旧合同绕过检查。

该合同用于本轮新开发题；历史`evidence-v1`保留原来的规范body口径，274题的hash/标签/历史结果不改变。不能混比两套条件保留率。

新增12题首批开发pilot（睡眠9、聚餐腹痛3；其中追问2），每题绑定文档版本、body hash和来源范围。题目由开发者根据原文设计并已暴露，不是独立验证集，也不等于计划120开发/80验证/40流程已完成。没有据此调阈值。

加入严格实验入口检查后，最终116项相关测试联合通过，日志`logs/stage3-source-final-tests.log`。这是软件合同/隔离数据测试，不是116次真实模型评测；真实pilot结果另记。

## 首轮真实模型结果

实际执行代码`a582437`，tracked_changes=false；本地`bge-small-zh-v1.5`、`bge-reranker-base`，CPU2线程，180-token子块、256-token句对、每次最多5块/每篇2块。隔离内存Chroma为73篇/347子块，运行结束即释放，不打开在线持久化索引。

| 指标 | hybrid | rerank |
| --- | --- | --- |
| 目标文档保留 | 12/12 | 12/12 |
| 最终逐字标注范围 | 13/14 | 13/14 |
| 标注条件 | 2/2 | 2/2 |
| 实际重排输入标注范围 | 不适用 | 12/14 |
| 首次后查询P95 | 42.06ms | 2621.12ms |

0逐题错误、0重排降级。进程峰值工作集1366.7MiB，运行前可用7142.5MiB；无生成API调用。这里只是两主题12个正例的顺序单次运行，没有负例/独立验证/HTTP/LLM开销，不能拿来宣称全量质量或在线性能验收。

具体失败保留在`backend/medical/evaluation/results/source_pilot_first_v1.json`：

- hybrid的SOP09找到睡眠文档，但没有选中“影响日常工作后寻求帮助”的标注范围；rerank修复此题。
- rerank的SOP03同样找到睡眠文档，却漏掉规律作息标注；该范围未进入记录的8块候选池。
- SOP08有一个求助范围未进入子块候选池/实际重排输入，但最终父段扩展补齐。不能把父段补齐误写成重排模型已经看到了它。
- 96个实际句对最长187 tokens，原始句对最长194，均在256以内；目标标注范围没有出现“池内有、编码后丢失”。后续重点仍为候选范围和最终同文档段落选择。
- 5题的其他候选包含4篇待补映射资料中的一部分，取证工具保守标为unverified trace；未知来源ID均不属于该题gold文档。目标gold来源可验证，不代表全部96个候选均具备原页映射，不能宣称所有来源映射零缺失。

取证只重建真实记录的chunk与模型可见坐标，没有再次运行神经模型，也没有修改gold、阈值或候选配额。摘要绑定原报告SHA256、实验代码、分析代码、模型/分词器资产、语料及sidecar hash。旧报告均保留。

覆盖清单也已支持指定corpus，并在新快照中纳入睡眠新资料：`stage3_coverage_inventory_v2.json`。19主题仍为13个部分覆盖、6个缺少专门来源；没有因为新增1篇就标成完整覆盖，原72篇baseline统计不受影响。

## 复现

需要本机已保存的固定hash原料。缺少原料时明确失败；完整新环境原料安装流程仍在阶段6范围，不以代码可运行代表已完成新环境验收。

从`backend`执行：

```powershell
# 构建必须指定全新目录，不能覆盖现有快照。
.\.venv\python.exe -m medical.build_sleep_snapshot --output ..\medical-rag-data\datasets\official-zh-v2\2026-10-17
.\.venv\python.exe -m medical.audit_source_snapshot --snapshot ..\medical-rag-data\datasets\official-zh-v2\2026-10-17 --output <新的审计JSON路径>
.\.venv\python.exe -m medical.experiment --suite medical\evaluation\source_pilot_suite_v1.json --corpus ..\medical-rag-data\datasets\official-zh-v2\2026-10-17\corpus --source-snapshot ..\medical-rag-data\datasets\official-zh-v2\2026-10-17 --metric-contract source-evidence-v1 --profiles hybrid rerank --input-policy query_first_v1 --chunk-strategy token-v1 --child-tokens 180 --rerank-max-length 256 --output <新的实验JSON路径>
```

## 当前尚未完成

这里只新增1篇资料，并修正一处旧节选，不能称作规模化扩容完成。其他主题原文、4篇历史快照、全库人群范围治理、独立验证集、排序/充分性校准、答案/Agent评测、性能和原子发布都继续按六阶段计划推进。新策略仍未通过全部发布门槛，不能直接替换在线配置。临床审核按用户安排暂缓；逐字校验不等于临床审核、语义充分或公开使用许可。
