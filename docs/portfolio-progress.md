# Aide 升级进度与交接记录

更新：2026-10-06。主方案：`portfolio-upgrade-plan.md`。

## 当前状态

| 任务 | 状态 | 实现/产物 | 验收/限制 |
| --- | --- | --- | --- |
| M0 方案与基线 | 已提交 | `0c255f1` | 根据当前代码审计，不把旧报告指标当本轮结果 |
| M1a 统一检索实验 | 已实现并验收 | `8393673`；suite/experiment/指标测试 | 43题四模式真模型对照完成；已有154题锁定，未新增240题 |
| M1b 新冻结题集 | 待开发 | 目标约240题 | 不是当前已完成题数，不宣称外部盲测 |
| M1c 答案与任务评分 | 待开发 | 计划 judge adapter / 声明依据 / 成本报告 | 数字审计已存在，完整语义尚未完成 |
| M2a 时间与幂等 | 已实现并验收，待提交 | health_time / receipts / API与MCP更正 / admin | 19项专项/API测试；幂等仍要求调用方传稳定key |
| M2b 身份与更正历史 | 开发中 | 可信上下文绑定、修正快照 | 正在核对SDK与聊天消息来源；未验收 |
| M2c 记忆读取与日历闭环 | 待开发 | 已有 CRUD/日历，继续增强 | 不能只凭旧页面可打开判全部完成 |
| M3 中文资料流水线 | 待开发 | 已有 registry / hashes / isolated pilot | 仍需 staged切换、适配切片、覆盖扩容 |
| M4 编排可靠性 | 待开发 | 已有 Triage 专员工具 | 状态/预算/取消/幂等协作待补 |
| M5 追踪和面板 | 待开发 | 已有部分检索日志 | 统一 trace 与隐私/保留策略待补 |
| M6 CI / 故障 / 交付 | 待开发 | 已有 Windows launcher | 新环境与真实故障矩阵待验 |

## 2026-10-06 审计发现

- `health_tools._resolve_observed_at` 把有 offset 的 ISO 直接去掉 tzinfo，导致日期/时刻偏移；仅说“20号”会自动猜上月，事实可能错写。
- 工具更新接口只支持摘要/详情，无法修正 observed_at；省略详情时默认 `{}` 可能覆盖旧信息。
- 健康记录服务缺少幂等回执，重复工具调用会生成重复记录；服务 update 接受任何模型属性，须限制可修改字段。
- 现有医疗评测 MRR 未截断在 K；主命令未统一报告数据/参数/提交版本。历史指标要注明定义差异。
- 本轮开始时正式代码没有 tracked修改； `.claude/`、`.fastmcp/`、根 package 文件、简易 server 和前端性能实验仍本地保留。

## 后续执行规则

每次继续先读本文件、查看 git status/log，完成一个有验收边界的任务再更新状态。记录 failed/fallback/已知回归，不能修改标签抬分。不读取 .env 密钥作输出，不默认上传个人健康事实。

## 2026-10-06 已执行

- 联合64项离线/临时SQLite/ASGI测试通过。包括新评估契约8项、健康记忆16项、健康API3项及既有检索/协作/医疗依据测试；不等于64条真实用户聊天验收。
- 固定43题、4模式的真实BGE/reranker实验完成，报告 `backend/data/evaluation_reports/retrieval_baseline_20261006_v1.json`，complete=true。具体结果见 `retrieval-experiment-baseline.md`。没有生成API调用。
- 规范JSON哈希兼容Windows/Linux换行；旧MRR升级TopK截断，历史指标不可直接混比。
- 实际迁移 `health_record_admin` 返回 prepared；备份为 `backend/data/backups/health-before-receipts-20261006-153706-055259.sqlite`。只增加回执表，没有重写既有健康事实。
- 既有Pydantic、Starlette TestClient弃用提示仍存在；LiteLLM价格表联网失败后使用包内备份。未为消除提示盲目升级依赖。
- 目前未重新启动服务、未做MCP HTTP/生成模型/日历页面全闭环；健康工具的可信身份与自动消息级幂等待M2b。

下一步：保存M2a提交，再完成M2b身份与修正历史。未执行的测试不标通过。
