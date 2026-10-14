# 病历解析：接入设计与第一版实现

## 范围与基线

- 分支：`codex/medical-record-parser`，基点 `5b2b1b7`。
- 用户已确认第一版演示 **门诊病历 / 出院小结**。
- 保存交互采用当前设计默认值：解析后核对、可修正、点击确认才生成身体状况记录。解析成功的待核对结果会先持久化。
- 上传、粘贴、Agent 调用共用服务，模型抽取与健康记录写入分开。

## KnowResume 的复用边界

参考仓库：https://github.com/18haventgirl/KnowResume

固定参考版本：`691f4140ce18f9b8ed6c31cfdd06f2693a4feaa3`。

已读取 `smartresume/backend/resume_analyzer.py`、`data/file_processor.py`、`data/ocr_provider.py`、`data/text_extractor.py`、`model/llm_client.py`、`utils/prompts.py` 和 Flask 演示入口。该版本的包名是 `smartresume`；README 中的 `from KnowResume import ...` 与源码不一致。项目 `pyproject.toml` 标注 Apache-2.0，许可证位于 `docs/LICENSE`。

采用其“文档取字 → 必要时 OCR → 一次模型抽取 → 后处理”的分层方式，使用相同的 RapidOCR ONNX 方案。Aide 的解析模块为针对病历重新实现的代码，没有整体导入该项目，也不运行它的 Flask 服务。简历专用字段、地址归一化、简历微调模型、版面 YOLO 和错误时落盘全文的逻辑没有迁入。

| 原项目职责 | Aide 实现 |
| --- | --- |
| FileProcessor / TextExtractor | `backend/medical_parser/documents.py`：PDF 文字层、DOCX 段落/表格、TXT、图片及扫描 PDF OCR |
| ResumeAnalyzer | `MedicalDocumentService.parse`：容量限制、解析、字段抽取、结果保存 |
| LLMClient / resume prompts | `extractor.py`：病历字段协议、OpenAI 兼容接口、原文依据校验 |
| DataProcessor.post_process | `ground_result`：引用存在性、原文片段、否定及不确定限定词检查 |
| 独立 Flask demo | Aide Dashboard 顶部“病历解析”工作区，沿用认证和 API 客户端 |

## 后端规范

数据流：认证用户 → 限量读取文档 → 行编号 → 模型 JSON → 校验 → 待核对记录 → 用户确认 → 同一事务写健康记录并标记已确认。

`medical-record.v1` 包含姓名、性别、年龄、医疗机构、科室、就诊/入院/出院日期、主诉、现病史、既往史、过敏史、查体与检查、原文诊断、诊疗经过/用药、医嘱/随访。每个字段包含 `value`、`evidence` 和状态；原文行保存页号、行号、提取方式及可用的 OCR 置信度。

1. 值必须是引用原文中的连续片段；引用不存在或无法核对的值留空并产生提示。
2. 诊断等字段丢失“否认、疑似、待排、未”等原文限定词时留空。该校验保守，可能漏提取；不等同于医学准确率保证。
3. 缺失内容保持空白，不自动填写“无”。日期保留原文形式，保存时要求用户确认完整日历日期，不用上传时间冒充就诊时间。
4. `medical_documents` 是新增表；解析全文和原结果持久化，确认后另存修正值。原文件字节不落盘。
5. `health_records.source=document`、`confidence=user_confirmed`。新增来源值使用已有字符串列，无需重建旧表。
6. 确认采用数据库条件更新与同一事务，重复及并发确认只生成一条健康记录。
7. 所有查询、确认、删除从登录身份获得 user_id，客户端不能指定归属用户。跨用户访问返回 404。
8. 删除解析记录会删除其原文及提取结果，已经确认生成的健康记录仍可独立保留或在身体状况界面删除。
9. 模型错误响应和请求校验错误不回显病历全文。解析不调用外部搜索或执行文档内指令。

### API

统一返回 Aide 的 `{success, data, message, ...}`，失败使用 HTTP 状态码和 `detail`。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/medical-documents/parse-file?filename=...` | 原始二进制请求体；避免 multipart 预先无限写临时文件 |
| POST | `/api/medical-documents/parse-text` | JSON `{text, name?}` |
| GET | `/api/medical-documents` | 最近 50 个成功解析记录的摘要 |
| GET | `/api/medical-documents/{id}` | 原文、字段及已确认修正值 |
| POST | `/api/medical-documents/{id}/confirm` | `{fields: {字段名: 文本}, observed_date: YYYY-MM-DD}` |
| DELETE | `/api/medical-documents/{id}` | 删除该用户的解析记录 |

支持最大 10 MB、12 页 PDF、4 万字符。DOCX 限制 ZIP 条目和解压体积；含内嵌图片时要求转换 PDF，避免只提取文字而遗漏关键图像。每个进程最多同时解析两份文档，繁忙返回 429。同步 HTTP 等待结果，模型超时 90 秒且不自动重试，前端及 Vite 对解析路由等待 180 秒。

### 专门的 Agent

`Medical Record Parser Agent` 已注册到现有 Agent 管理器，Triage 将“解析/整理门诊病历或出院小结”交给它。工具只接收用户提供的完整文字，从运行上下文获得用户身份，复用解析服务。Agent 返回待核对记录编号；上传文件通过前端完成。该 Agent 没有确认保存工具，健康记录仍需界面确认。

## 前端融入

- Dashboard 顶部增加“聊天 / 病历解析”，解析时使用宽工作区；切回聊天保留当前解析界面状态。
- 初始页：上传/粘贴切换、文件限制、两个明确标注虚构的样例、正在解析和可重试错误提示。
- 结果页：桌面双栏，左侧原文，右侧分组字段；窄屏纵向排列。点击字段依据定位并高亮原文行。
- 当前上传的图片/PDF 可在内存中预览；从历史重新打开时展示留存的提取原文，不宣称仍保存着原文件。
- PDF 使用按需加载的 PDF.js 在页面内渲染，支持翻页和下载原文件；不依赖浏览器内置 PDF 插件。字体、CMap 和 WASM 由 Vite 从锁定的依赖生成到 `ui/public/pdfjs/`，随构建一同发布，不使用外部 CDN。该生成目录不入 Git。
- 空白、待核对、人工修正分别标识；修改后依据按钮标注“修改前的提取依据”。
- 底部确认日期及保存按钮；保存成功后标注已保存并刷新个人数据组件。
- 最近记录支持重新打开、刷新、删除；没有把接口失败当成空历史。

## 运行与配置

基础依赖沿用 `backend/requirements.txt`，文字 PDF、DOCX、TXT 不需要 OCR 包。

图片、扫描 PDF 和带图片的混合 PDF 需要额外安装：

```powershell
python -m pip install -r backend/requirements-medical-parser-ocr.txt
```

模型默认复用 `OPENAI_API_KEY`、`OPENAI_API_BASE_URL`、`OPENAI_CHAT_MODEL`。也可用 `MEDICAL_PARSER_API_KEY`、`MEDICAL_PARSER_BASE_URL`、`MEDICAL_PARSER_MODEL` 单独配置，模型服务需支持 JSON object 响应。RapidOCR 本地运行，提取出的文字发送给已配置的模型。

服务启动时通过现有 SQLAlchemy `create_all` 创建新表；正式环境若禁用 DDL，需要运维预先建表。前端运行现有 Vite，后端运行现有 FastAPI；解析路由已单独延长代理超时。

## 验证与边界

可重复检查（在已安装后端基础及 OCR 依赖的测试环境执行；生成器还需要 `python-docx`、`reportlab` 和中文字体，如 Windows 微软雅黑或 Linux Noto Sans CJK）：

```powershell
python -m pip install python-docx==1.2.0 reportlab==4.4.9
python backend/tests/create_medical_parser_fixtures.py logs/parser-format-matrix
$env:MEDICAL_PARSER_TEST_FIXTURES = (Resolve-Path logs/parser-format-matrix).Path
cd backend
python -m unittest tests.test_medical_parser tests.test_agent_coordination -v
cd ../ui
npm run typecheck
npm run build
```

测试覆盖 TXT、DOCX、文字 PDF、PNG、JPG、JPEG、扫描 PDF、混合 PDF，以及原文顺序、输入限制、DOCX 图片防遗漏、PDF 页数与密码保护、虚构字段/伪造引用/丢失限定词、基础字段名前缀清理、用户隔离、确认前不入健康记录、人工修正留痕、并发确认、删除和 API 流程。格式矩阵使用真实文件解码和本地 OCR，只替换远程模型；真实模型在浏览器流程中另行验证。不设置 `MEDICAL_PARSER_TEST_FIXTURES` 时会明确跳过矩阵测试，不能据此宣称全部格式已通过。具体实测记录见 `medical-record-parser-validation.md`。

第一版不做化验数值的专用表格识别，不生成新诊断或调整治疗，不支持手写保证、跨页病历拼接、批量异步队列或图像坐标框。原文校验只能校验取字后的文本；OCR 读错原件仍需人工发现。进程异常或请求断开时未完成解析不会自动恢复；确认已写入的结果可从最近记录恢复。真实脱敏病历的提取质量尚需样本评估。
