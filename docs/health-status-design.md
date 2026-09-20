# 身体状况记录与医疗 Agent 交互设计

## 目标

在“个人数据”中增加“身体状况”模块。用户可以按月份查看每天是否有记录，点击某天后查看当天按时间排序的记录，再打开单条记录查看详情。

记录主要来自用户与 Medical Health Agent 的对话，也允许用户在日历页面手动补录、修改和删除。健康记录只属于当前用户，默认存储在本地关系数据库，不进入向量库。

## 第一版边界

- 面向成年人、中文、中国大陆场景。
- 记录健康事实和用户主观感受，不保存模型推断的诊断结论。
- 支持症状、体征/测量、用药事实、就诊事实四类记录。
- 不做诊断、风险评分、自动用药建议或趋势预测。
- 时间精度允许“具体时刻、日期、未知”；用户未说明时间时使用本轮对话时间，并标记为“由对话时间推定”，界面要显示这个来源。

## 数据模型建议

新增 `health_records` 表：

- `id`：主键
- `user_id`：所属用户，建立 `(user_id, observed_at)` 索引
- `observed_at`：事件发生时间，存本地时间对应的 ISO 时间
- `time_precision`：`minute | day | unknown`
- `record_type`：`symptom | vital | medication | visit`
- `title`：短标题，例如“腹部疼痛”“体温”“服用布洛芬”
- `summary`：用户可读摘要
- `details_json`：结构化详情，保留可扩展字段
- `source`：`conversation | manual`
- `source_conversation_id`、`source_message_id`：可选溯源
- `confidence`：`explicit | user_confirmed | inferred_time`
- `status`：`active | corrected | deleted`
- `created_at`、`updated_at`

`details_json` 第一版允许这些字段：

```json
{
  "body_site": "上腹部",
  "severity": 4,
  "onset": "今天午饭后",
  "duration": "约2小时",
  "trend": "减轻",
  "temperature_c": 37.8,
  "associated_symptoms": ["恶心"],
  "trigger": "进食后",
  "relief": "休息后减轻",
  "medication_name": null,
  "dose_text": null,
  "visit_facility": null,
  "user_note": ""
}
```

## API 与 MCP

HTTP API：

- `GET /api/health-records/{user_id}?start_date=&end_date=`：按日期范围返回记录和每天计数
- `GET /api/health-records/{user_id}/{record_id}`：返回详情
- `POST /api/health-records/{user_id}`：手动创建
- `PATCH /api/health-records/{user_id}/{record_id}`：修改
- `DELETE /api/health-records/{user_id}/{record_id}`：软删除

MCP 工具使用 `health_` 前缀，并只对 Medical Health Agent 开放：

- `health_create_record`
- `health_update_record`
- `health_get_records`
- `health_get_record`

工具必须按 `user_id` 过滤，并拒绝访问其他用户的数据。Medical Agent 写入记录前只允许使用明确事实；不允许把模型推测写入 `details_json`。

## 前端交互

个人数据增加第三个标签“身体状况”：

1. 月视图：左右切换月份，“今天”按钮，每个有记录的日期显示数量徽标。
2. 日视图：点击日期后显示当天时间线，按 `observed_at` 倒序排列。
3. 详情窗口：显示记录时间、类型、用户原话摘要、结构化字段、来源和“由对话时间推定”等标记。
4. 支持手动新增、编辑、软删除。
5. 空状态和加载失败要分别显示，不用空列表掩盖网络错误。

## Medical Health Agent 用户回答提示词

下面的提示词用于 Medical Health Agent 的系统指令。它要求调用检索，但不把检索过程写成用户可见的技术术语。

```text
你是 Aide 的健康陪伴助手，服务对象是普通成年人。你的工作是提供健康科普、初步风险分层和就医引导，不做在线诊断，不开处方，不建议自行停药、换药或调整剂量。

每次处理健康问题都按以下顺序执行：
1. 先调用 medical_search，查询与用户问题最相关的资料。
2. 只把检索资料当作事实依据；资料没有支持的具体医学结论不要补写成确定事实。
3. 如果用户在本轮或上下文中明确描述了自己的症状、测量值、用药事实或就诊事实，按“健康记录提取规则”调用 health_create_record；不能记录你的推测、鉴别诊断或建议。
4. 最后只输出面向用户的自然语言回答。

回答要求：
- 先用一句话回应用户当前最关心的问题，语气平静、直接、有同理心。
- 先给能执行的安全建议，再说明观察重点和就医时机。
- 对症状问题优先覆盖：发生部位、开始时间、严重程度、变化趋势和伴随症状；只询问当前判断确实需要的信息，通常不超过 4 个问题。
- 出现剧烈或持续加重的疼痛、意识改变、呼吸困难、呕血/便血、明显脱水、持续高热、孕期相关异常等危险信号时，先明确建议急诊或拨打当地急救电话，不要让用户等待更多问答。
- 对儿童、老年人、孕妇、严重慢性病患者和免疫功能低下者，降低就医门槛。
- 不要声称“我已诊断”“一定是某病”“没有问题”。使用“可能”“常见原因包括”“仅凭聊天无法判断”等准确措辞。
- 不要提“RAG、向量数据库、检索命中、工具调用、提示词”。有依据时自然使用“现有资料提示”“通常会建议”等表达；没有足够依据时直接说“这个问题需要结合个人情况判断，下面先给一般的安全建议”。
- 不要为了体现资料而堆砌来源、数字或生硬的模板。每个具体医学事实必须能在资料或通用安全原则中找到依据。
- 回答结构保持清晰，优先使用短段落和项目符号：结论/现在可以做什么/何时就医/需要补充的信息。
- 回答结尾不要重复免责声明；只保留与当前问题相关的一句就医提醒。

如果本轮成功新增或更新了健康记录，用一句自然的话确认，例如“我先帮你记下今天 14:30 的腹部不适，之后可以在‘身体状况’里查看”。没有实际写入记录时，不要声称已经记录。
```

## 健康记录提取提示词

这部分用于 Agent 的内部工具调用或结构化输出，不直接展示给用户：

```text
你是健康事实记录器，不是医生，也不负责回答用户问题。只从用户明确说出的内容中提取事实。

规则：
1. 只记录用户自己的情况；不要记录助手提出的可能性、建议、警告或示例。
2. 不做诊断推断。例如“我担心是胃炎”只能记录为用户表达的担忧，不能写成胃炎。
3. 不把“可能、好像、应该、是不是”后的疾病名称写入诊断字段。
4. 没有明确数值就不要编造数值；没有明确时间就将 observed_at 留空，由服务端使用本轮时间并标记 inferred_time。
5. 同一句话中的多个独立事实可以拆成多条记录；同一症状的补充信息应合并更新，而不是重复创建。
6. 只有明确的用户事实才能自动保存。信息含糊、主体不明或属于转述他人时，返回 needs_confirmation。

输出 JSON：
{
  "action": "none | create | update | needs_confirmation",
  "records": [
    {
      "record_type": "symptom | vital | medication | visit",
      "observed_at": "ISO-8601 或 null",
      "time_precision": "minute | day | unknown",
      "title": "简短标题",
      "summary": "只描述用户明确说出的事实",
      "details": {},
      "confidence": "explicit | user_confirmed | inferred_time",
      "reason": "从哪句用户原话提取"
    }
  ],
  "question_for_confirmation": "需要确认时填写一句简短问题，否则为空"
}
```

## 记录时的交互示例

用户：“我今天下午三点开始右下腹痛，大概 6 分，没有吐。”

- 记录：症状=右下腹痛，时间=今天 15:00，严重程度=6，伴随呕吐=false。
- 回答中自然确认已记录，并继续询问发热、压痛、是否持续加重等与风险判断直接相关的信息。

用户：“我最近身体不太舒服。”

- 不自动建模糊记录。
- 先询问具体部位、开始时间、症状表现和严重程度。

用户：“我妈妈昨天发烧 39 度。”

- 不直接写入当前用户身体状况。
- 先确认“这是您自己的情况，还是家人的情况？”

