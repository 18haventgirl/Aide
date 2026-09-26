# 华佗 Lite 中文候选数据试验

更新：2026-09-26。状态：下载、筛选、关键词建库及 5,000 条 BGE 向量建库完成；8 个中文向量查询冒烟验证通过；未接入正式回答。

## 2026-09-26 续建验证

- 复用 3,088 条已保存记录，新增 1,912 条，最终 Chroma 记录数 5,000。
- 本轮建库耗时 203.16 秒，进程峰值工作集 546.9 MiB；启动可用内存 2,414.4 MiB，结束时 2,363.1 MiB。
- 独立进程重新打开索引，核对样本 SHA256、模型权重 SHA256 和记录总数；使用 BGE 查询指令进行 8 个中文问题的 Top-3 检索，全部完成。向量维度为 512。
- 首次查询含模型加载耗时 4,227.5 毫秒，后续耗时见本地 `indexes/pilot-5000-adult-general-screen-v1/dense_smoke.json`。这不是线上端到端延迟测试。
- 检索结果仍有场景不精确问题，例如久坐活动问题召回痔疮、腰痛相关问答。尚无人工相关性标签，不能据此报告召回率或宣布质量达标。混合检索与 rerank 评估尚未完成。
- 下文的内存中断描述保留为 9 月 24 日的历史记录，当前断点续建已完成。

## 数据及存储

- 数据集：FreedomIntelligence/Huatuo26M-Lite，非模型权重，不需要部署华佗语言模型。
- 来源：[原始数据卡](https://huggingface.co/datasets/FreedomIntelligence/Huatuo26M-Lite/blob/main/README.md)。社区问题、模型改写回答，不能当作官方医学原文。
- 下载使用发布者的 ModelScope 仓库；版本、字节数和 SHA256 固定在 `registry/huatuo_lite.lock.json`，与原始文件校验值核对一致。
- 数据提供者声明 Apache-2.0；逐条上游来源及授权尚不完整，保留为本机研究候选。
- 根目录：`D:\Workplace\Aide\medical-rag-data\datasets\huatuo26m-lite\hf-90ce61699e90`。
- 子目录：`raw` 原始 JSONL、`screened` 筛选审计 SQLite、`normalized` 候选 JSONL、`indexes` 实验索引、`reports` 运行结果。
- 文件名规则：`huatuo26m-lite__版本前12位__阶段.扩展名`。大文件和索引已排除 Git，代码、锁定文件及报告纳入版本控制。

## 实际处理结果

| 项目 | 结果 |
| --- | ---: |
| 原始字节数 | 138,220,325 |
| 原始记录 | 177,703 |
| 规则排除 | 170,030 |
| 规则通过但未经核实 | 7,673 |
| 确定性抽样 | 5,000 |
| SQLite FTS5 索引记录 | 5,000 |
| FTS 索引字节数 | 15,695,872 |
| 筛选进程峰值内存 | 38.3 MiB |
| FTS 建库进程峰值内存 | 123.4 MiB |
| FTS 建库耗时 | 5.31 秒 |

样本 SHA256：`c4e15654027aa6c17610ece61d44d53b6ed8dba5710bd48b50260d83de7e52da`。

筛选检查中文比例、长度、主题、年龄范围、药物和操作建议、联系方式、提示注入及重复问题。主题按问题判断，避免因答案泛泛提及饮食休息而误纳入。筛选通过只表示符合试验规则，所有记录仍为 `answer_eligible=false`。

## 切片与检索

每个问答保留为一个完整单元，问题和回答合计不超过 450 字符。向量建库另用真实 tokenizer 验证不超过 512 token，超长报错，禁止静默截断。保留原始行号、记录 ID、版本及审核状态。

关键词通道使用 jieba 分词和磁盘 SQLite FTS5/BM25。此通道是独立试验，不表示生产检索已经改为 FTS5。8 个问题已做实际关键词检索冒烟检查；没有人工相关性标签，因此不能报告召回率。

向量脚本复用本机 BGE-small-zh-v1.5，CPU 两线程、编码 batch=4、每 16 条持久化，支持续建。启动前要求可用内存至少 1536 MiB，批次前至少 768 MiB。本次在约 2.5 GiB 可用内存时启动，完成 3,088 条后系统可用内存下降至 716.5 MiB，保护机制中止建库。建库进程峰值工作集为 556.3 MiB。尚未产生完整可验收的向量索引，也未完成此批数据的混合检索和 rerank 评估。重新执行 dense 命令会跳过已保存记录。

## 内容质量检查结论

抽查仍发现缺少依据或可能误导的回答，例如 HTL-13485745 关于午睡时长的倍数说法、HTL-8868029 关于橙子与支气管痉挛的说法；跑步后咽痛问题也有非运动场景结果。模型自评分不能替代来源核对，关键词过滤不能解决医学真实性问题。

因此本批数据不直接升级成正式健康证据。下一步先完成资源允许时的向量试验，再使用有来源的中文资料核对候选主题；无法核对的条目保留为查询研究素材，不自动发布。正式知识库继续使用此前中文内容。

## 复现与续建

在 `D:\Workplace\Aide\backend` 执行：

```powershell
.\.venv\python.exe -X utf8 -m medical.huatuo_lite download --endpoint https://modelscope.cn --proxy http://127.0.0.1:7890
.\.venv\python.exe -X utf8 -m medical.huatuo_lite prepare --limit 5000
.\.venv\python.exe -X utf8 -m medical.huatuo_pilot_index fts --limit 5000
.\.venv\python.exe -X utf8 -m medical.huatuo_pilot_index search --limit 5000 --query "成年人如何改善睡眠"
.\.venv\python.exe -X utf8 -m medical.huatuo_pilot_index dense --limit 5000
.\.venv\python.exe -X utf8 -m medical.huatuo_pilot_index dense-smoke --limit 5000
.\.venv\python.exe -X utf8 -m unittest tests.test_huatuo_lite tests.test_medical_data_registry
```

代理地址仅适用于本机已运行该代理时。下载完整且校验通过时直接复用本地原始文件。

最新回归：11 个测试通过，覆盖中文筛选、风险规则、来源标识、完整性校验、去重、确定性抽样、中文 FTS 查询和低内存拒绝加载。不能把这些测试解释成医学正确性或向量检索质量验收。
