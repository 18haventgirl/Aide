# 回答数量依据筛查（2026-09-29）

## 目的与实现

针对上一轮头痛回答额外添加“记录4–8周”的问题，增加 `backend/medical/answer_audit.py`。
输入回答和本次实际检索 hits，抽取带单位的阿拉伯数字数量，按范围连接符、全角字符和部分单位别名归一化，输出未在资料出现的数量及可匹配文档 ID。

`verify_agent` 的 grounded / not_covered / unavailable 场景现在分别附带 `quantity_audit`；原 `passed` 仍只代表模型/工具连通性，不能理解为医学内容验收通过。

## 边界

- 不匹配不等于错误：模型的通用知识、用户提供的事实、单位换算都可能产生资料之外的数值。
- 匹配也不等于支持：例如“不要等5天”和“必须等5天”会出现相同数量；状态明确标注 `lexical_match_only`。
- 当前未覆盖中文数字、所有单位、跨句推理、单位换算、时间上下限语义，也不评估无数字的错误医学断言。
- 仅在显式离线/合成验收运行，不向线上日志写入用户病情，不自动删除或重写回答，不用它阻止 LLM 回复。
- 本次工具是开发筛查基础，线上回答质量问题尚未因此完全解决。

## 测试和使用

新增 7 项测试：已观察到的无来源时长、全角/范围/单位归一化、不同单位、防止把序号/链接当数量、否定语义边界、无证据、去重。与引用/来源测试合计 14 项通过。

真实 DeepSeek 验收三场景均完成，各调用检索工具一次：grounded 3739 tokens、not_covered 3195 tokens、unavailable 2940 tokens。前者抽取 8 个数量，1 个“20–30分钟”未在返回证据出现；后两者分别 7/7、9/9 未匹配（本来没有资料，不能将它们直接视为错误）。证明该工具能揭示“连通性通过但数量依据不足”的差异，尚未证明最终回答事实正确。

在 backend 目录：

```powershell
& .venv/python.exe -m unittest tests.test_answer_audit tests.test_medical_grounding tests.test_official_excerpt
# input.json: {"answer":"...", "hits":[{"doc_id":"...", "text":"..."}]}
& .venv/python.exe -m medical.answer_audit input.json --output report.json
# 以下显式调用官方 DeepSeek，会产生 API 费用，使用合成问题：
& .venv/python.exe -m medical.verify_agent --live --output ../medical-rag-data/datasets/chinese-official/2026-09-29/reports/agent_quantity_audit.json
```
