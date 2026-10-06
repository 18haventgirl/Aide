# Aide 升级进度与交接记录

更新：2026-10-06。主方案：`portfolio-upgrade-plan.md`。

## 当前状态

| 任务 | 状态 | 实现/产物 | 验收/限制 |
| --- | --- | --- | --- |
| M0 方案与基线 | 已提交 | `0c255f1` | 根据当前代码审计，不把旧报告指标当本轮结果 |
| M1a 统一检索实验 | 已实现并验收 | `8393673`；suite/experiment/指标测试 | 43题四模式真模型对照完成；已有154题锁定，未新增240题 |
| M1b 新冻结题集 | 待开发 | 目标约240题 | 不是当前已完成题数，不宣称外部盲测 |
| M1c 答案与任务评分 | 待开发 | 计划 judge adapter / 声明依据 / 成本报告 | 数字审计已存在，完整语义尚未完成 |
| M2a 时间与幂等 | 已提交并验收 | `0151783`；health_time / receipts / admin | 初阶段19项专项/API测试；后续消息级绑定见M2b |
| M2b 身份与更正历史 | 后端已实现，契约/API验收通过 | SDK本地health工具、来源绑定、版本/历史 | 真实模型及页面完整链路待M2c；端口占用阻挡运行更新 |
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
- M2b续轮联合78项测试通过，日志 `logs/portfolio-regression-tests.log`。真实SDK FunctionTool边界、同消息创建重放、跨用户读写拒绝、消息存储ID、更正历史、历史失败回滚、两线程版本竞争均通过；没有调用生成API。
- M2b迁移新增version/history表前再次备份：`backend/data/backups/health-before-receipts-20261006-195738-279174.sqlite`。旧记录只建立revision=1基线，没有伪造旧历史。
- 运行更新检查发现8000 PID28624启动脚本为 `C:/Users/HONOR/.codex/worktrees/207d/Aide/logs/parser-preview-server.py`，属于另一工作树预览；未停止。当前工作区的API/MCP更新未完成，不宣称新代码已在线生效。M2c需处理可配置端口或在8000空闲后进行整链路验收。
- 没有完成真实MCP HTTP/生成模型/日历页面全闭环；后端验收不能替代页面验收。

下一步：保存并推送M2b；继续M2c日历更正/历史窗口、准确月份统计、跨会话周摘要与模型/页面验收。新冻结题集及语料流水线仍按主方案推进。未执行的测试不标通过。
