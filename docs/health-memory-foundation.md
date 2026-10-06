# 健康记忆基础：时间、幂等与更正

日期：2026-10-06。对应主方案 M2a。M2b 的可信工具身份绑定、消息级自动幂等与更正历史，以及 M2c 的完整页面闭环尚未完成。

同日后续：M2b实现见 `health-tool-context-and-history.md`；本文件保留M2a边界及验收。最新状态以portfolio-progress为准。

## 时间契约

数据库仍存 China UTC+8 无时区墙钟时间，保持既有结构。HTTP 输入带 offset 时先转为中国时间，再去掉 tzinfo；不使用运行主机时区猜测用户日期。

MCP 共用 `health_time.resolve_health_time`：

| 输入 | 行为 |
| --- | --- |
| 昨天/前天/上周三 | 相对于参考中国日期解析；跨月跨年正常 |
| 完整年月日 | 保存该日，未给时刻标记 day |
| 昨天晚上 | 保存昨天，具体时刻未知，不伪造为20点 |
| 完整日期+下午3点半 | 保存明确15:30，标记 minute |
| 带 offset 的 ISO | 转为中国时间，日期可能跨日 |
| 20号 / 没有年份的9月20日 | 返回 needs_clarification，不猜月份/年份 |
| 多日期、冲突、无效或未来事实 | 返回具体澄清问题，写入不发生 |
| 未说明发生时间 | 使用参考时刻，标记 unknown/inferred_time |

解析器不覆盖所有中文自然语言时间，也不是事实提取模型。其职责是避免无法确定的表达静默写错。解析版本和原表达保存在 details 内部 `_time`；API 只返回可读 `time_expression`，不把内部字段显示为健康事实。已有旧记录不回填或自动修正。

## 创建幂等

新增 `health_record_receipts`：user_id、key_sha256、payload_sha256、record_id。唯一约束是 user_id+key_sha256；记录和回执在同一事务提交。并发请求的失败事务同时回滚新记录，不留下孤儿事件。

- 同用户、同 key、同原始请求：返回同一记录 ID。
- 同 key 换内容：HTTP409，MCP显式失败。
- 不同用户同 key：独立。
- 记录已软删除后重放旧 key：冲突，不复活。
- unknown 时间的重试保留首个推定时间，不因重试时刻变化冲突。
- 记录已更新后原创建请求重放：返回原 ID 当前状态，不覆盖修正。

HTTP create 和 MCP create 支持可选 `idempotency_key`。没有 key 时保持普通新增语义。**当前没有完成将 Agent 的 key 自动绑定到可信消息上下文；仅增加字段不等于所有对话已自动去重。**下一模块把 user/conversation/message 与 key 放到可信执行上下文，不依赖 LLM 自行生成随机 key，也不以相似内容合并不同事件。

## 更正与错误语义

更新服务只允许 observed_at、time_precision、record_type、title、summary、details，拒绝修改所有权、主键、状态和来源。MCP update 支持更正日期/时刻；未传摘要/详情保持原内容，传入详情按字段补充，时间解析失败不写入。

API PATCH 拒绝显式 null，避免 observed_at=null 被错误转换为“现在”。时间范围包含当天最后一个微秒。数据库异常向上返回错误，不再伪装成无记录。更正前后历史与并发更新版本冲突仍待 M2b 实现。

## 迁移与回退

在 backend 目录：

```powershell
.\.venv\python.exe -m service.services.health_record_admin
```

对现有 SQLite：先 backup API 保存完整数据库到 `backend/data/backups/health-before-receipts-*.sqlite`，检查备份 integrity_check，再创建回执表。重复执行返回 already_prepared。新安装继续用现有 create_tables。

旧 health_records 结构和数据不变；回退代码保留新增表，不删回执/用户记录，不用整库备份覆盖新产生的其他数据。备份用于灾难恢复；实际运行迁移情况另记在进度表。API/MCP 须重启后加载新代码。

## 验证范围

`tests.test_health_memory` 使用真实临时 SQLite，包含跨线程两个事务同时写相同 key、用户过滤、删除重放、日期、更正、备份与重复迁移。`tests.test_health_record_api` 使用真实 ASGI 路由和临时 SQLite，仅替换身份/服务依赖，验证409/403/422/500和时区转换。

MCP 工具测试调用注册后的函数，未经过实际 MCP HTTP 或生成模型；不能解释为全部聊天闭环验收。没有修改用户事实、重算旧记录或发起健康问题 LLM 调用。
