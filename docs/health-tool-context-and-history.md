# 健康工具可信上下文与更正历史

日期：2026-10-06，主方案 M2b。沿用统一模型与既有Agent SDK。

## 身份边界

参考 [OpenAI官方SDK上下文说明](https://developers.openai.com/api/docs/guides/agents/define-agents)：应用上下文可将鉴权用户、数据库等依赖交给本地工具，不需要作为模型参数。实现根据本机安装的SDK签名核对，没有升级SDK或换生成模型。

- Medical Agent 的4个 `health_*` 改为SDK FunctionTool：健康事实CRUD直接调用本地业务服务；`medical_search`等外部/检索工具仍走原MCP。
- 健康tool schema没有user_id、来源会话/消息或idempotency_key。owner从RunContextWrapper读取，记录source_conversation_id和source_message_id由后端绑定。
- WebSocket为每个请求复制用户上下文快照；保存用户消息成功后，将真实数据库message.id及中国参考时间传入Runner。写入缺少来源上下文时显式拒绝，不生成假的消息ID。
- AgentSession发现会话属于其他用户时，在加载消息前拒绝；缓存返回也核对default_user_id。
- 原localhost MCP不再注册健康CRUD，Agent过滤器也不放行旧health工具。旧 `mcp-serve/health_tools.py` 保留为兼容/历史函数参考，单元测试不代表它仍公开注册。

## 自动创建幂等

key由可信user+conversation+已保存message ID+event_index生成，模型不能覆盖。每条用户消息不同事件按0、1等稳定编号，重试同一事实使用同编号。请求语义由回执payload哈希校验：同编号不同内容返回冲突，防止静默覆盖；重复同请求不增加记录/版本/历史。不同消息里的相同文字仍是独立事实，不做相似内容自动合并。

这覆盖同一消息工具重放、进程/事务重试的固定输入；不等于任意语义改写都自动去重。模型换编号或前端把一次消息重新保存为新message ID仍可能产生不同事件，后续M4需要请求幂等和事件提取评测。

## 更正和并发

新增 `health_record_versions` 保存当前revision，`health_record_revisions`保存创建/更新/软删除历史。用户原始健康记录表无新增列，旧数据由迁移建立revision=1基线，不伪造旧更正历史。

更新采用条件版本推进，与事实更新及before/after快照同一事务。API PATCH支持expected_revision；SDK工具可传读到的revision，未传则以本次读取版本进行条件更新。过期或并发冲突返回409/revision_conflict；相同内容不推进版本。历史写失败时事实和版本一起回滚。

`GET /api/health-records/{user_id}/{record_id}/history` 返回用户自己的更正历史；他人/已删除记录不可读取。历史包含明确事实，存于本地用户数据库，普通运行日志不新增事实原文。日历历史查看窗口尚未接入，属于M2c。

## 验收与迁移

新增真实SDK FunctionTool测试：schema无身份参数、同消息重试、新消息独立、跨会话读当前用户、缺来源拒写、跨用户修正拒绝、上下文序列化隔离、旧MCP过滤、会话所属用户及真实保存message ID。存储专项补充更正快照、失败回滚、无变化更新、两线程版本冲突；API验证409和history权限。

使用临时SQLite、真实SDK工具包装及ASGI路由。没有发起生成API调用，没有用用户健康聊天跑评测；尚未宣称真实模型完整闭环通过。

现有库继续先运行 `python -m service.services.health_record_admin`：缺少任一辅助表时先backup+integrity_check，再补表并给旧记录建立版本基线。重复执行不重复迁移。回退代码保留辅助表和历史，不能删用户数据。

新代码必须重启本项目API/MCP，防止旧MCP健康CRUD仍在旧进程中公开。实际迁移、测试、启动和提交写入portfolio-progress。
