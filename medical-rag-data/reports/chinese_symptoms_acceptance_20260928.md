# 中文常见症状资料增补验收（2026-09-28）

## 本次变更

- 研究库由 68 篇 / 88 chunks 增至 72 篇 / 95 chunks；未删除原切片。
- 新增国家卫健委流感居家与就医、咽喉不适，福建卫健委头痛，北京天坛医院腹泻共 4 篇限定范围摘录。
- 保留 BGE-small-zh-v1.5、BM25、RRF、BGE-reranker-base。Huatuo 5000 条仍在隔离试验库，不进入回答依据。
- `usage_scope` 从 Chroma metadata 传入 MedicalHit 和 medical_search；此前检索结果丢失了此字段。
- 修复 MCP 字典型 text/content 包装无法提取 citations 的问题，避免已命中资料却不显示来源卡片。

## 资料与复现

清单：`medical-rag-data/registry/chinese_symptoms_20260928.json`。
其中正文是正常浏览器读取并逐段核对的 UTF-8 摘录快照，SHA256 **不是整个网页或 HTTP 响应的校验和**。人工选段、标题、Markdown 小标题已明确标注；没有将生成式改写当成原文。
福建头痛完整 HTML 另保存在 `medical-rag-data/datasets/chinese-official/2026-09-28/raw/fj-headache.html`，原文件哈希写入 locator。

公开可读不代表开放再分发许可；本批仅用于已授权的本机研究。`source_checked` 是原文核对，不是医务人员审核。未录入原文中热水熏蒸、具体处方和历史门诊时间等不适合本功能的内容。

在 backend 工作目录执行：

```powershell
& .venv/python.exe -m medical.import_official_excerpt ../medical-rag-data/registry/chinese_symptoms_20260928.json --output medical/source_corpus
& .venv/python.exe -m medical.cli sync --research --corpus medical/source_corpus
& .venv/python.exe -m unittest tests.test_official_excerpt tests.test_medical_grounding tests.test_medical_rag tests.test_pilot_retrieval
& .venv/python.exe -m medical.evaluate --cases medical/eval_cases_chinese_symptoms_v1.json --k 5
```

## 已完成验证

- 28 项单元/本地 Chroma 测试通过，覆盖篡改哈希、重复 ID、研究隔离、适用范围到工具、MCP text 包装到引用等。
- 10 条新增资料定向检索：Recall@1、Recall@5、MRR、nDCG@5 均为 1.0。这是开发者编写的小型验收集，不能代表整体用户问题召回率。
- 新集平均检索 2108.3ms，P95 8995.9ms（包含首次模型加载）；随后历史集平均 1118.7ms，P95 1433.4ms。
- 原 33 条历史集未修改标签：Recall@5=.644、MRR=.689、nDCG@5=.633、无答案拒绝 8/8、急症识别 5/5、追问 Recall@5=.9，保持原基线。
- 旧 VS02、VS04、VS07 已返回对应新增中文资料，但旧标签要求已移除英文 ID，仍计未命中。保留旧集是为了不通过换标签伪造提升。
- 官方 DeepSeek 实际调用三场景：grounded / not_covered / unavailable 均有工具调用和模型回答，token 分别 3771 / 3546 / 3140。空结果与故障采用注入工具状态，此项不是断网测试。
- 浏览器实际观察到 Triage → Medical Health Agent → medical_search → 新头痛资料 → 模型回答。重排实际 applied，41 个候选，重排 8 个，最终 2 个；检索耗时 1647.3ms。测试明确为科普而非用户病情，未触发健康记录工具。
- 来源解析修复后再次浏览器提交头痛日记科普，最终回答下方实际出现“资料来源”、福建卫健委可点击链接及“原文核对，本机研究”标识。
- 单独刷新 API 时曾因遗漏 UTF-8 环境导致 GBK 日志编码失败；随后使用项目 `启动Aide.ps1` 恢复并完成上述页面复验。浏览器控制台保留重启期间的断连错误，不能宣称本次控制台全程零错误。

原始评测与真实模型报告：`medical-rag-data/datasets/chinese-official/2026-09-28/reports/`（本地忽略 Git）。

## 手工测试

1. `健康科普：反复头痛时，头痛日记应该记录什么？` → 预期新福建来源、运行输出 reranker_status=applied。
2. `天气干燥，张嘴呼吸以后嗓子不舒服是什么原因？` → 咽喉资料；不得直接确诊。
3. `腹泻的时候怎么防止身体缺水？` → 天坛医院资料；不应自行给静脉补液指令。
4. `流感发烧在家休息需要注意什么？` → 国家卫健委流感资料；不得泛化为所有发热。
5. `聚餐后肚子越来越痛还频繁呕吐，该怎么办？` → 既有广州来源与就医提示。

## 仍存在的限制与下一步

- 泛化腹痛（旧 VS05）仍无足够匹配；本批并未补齐所有常见病。
- 流感材料不能覆盖所有发热，季节性咽部资料不能证明运动后咽痛正常。
- 浏览器测试回答出现来源之外的“记录4–8周”等补充，提示词尚不能保证每个数字都有证据。后续应增加答案级数字/来源支持核查，不能把检索测试通过当作回答质量全部通过。
- 本次尚未完成真实网络超时/取消、跨用户隔离、所有追问的浏览器故障矩阵；不要宣称全量端到端验收完成。

## 回退

代码使用本次独立提交回退；资料以此清单的 4 个 doc_id 为边界。要回退索引，先备份当前 corpus 到独立目录，在该目录排除这 4 篇后运行 sync（不要对用户笔记、个人向量库、Huatuo 集合做删除）。重新启动本项目 MCP/API 以清除旧缓存。原 68 篇源文件没有被本次修改。
