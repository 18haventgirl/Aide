# 工程收尾与可复现基线

日期：2026-10-01。对应优先级一；不把本轮当作新的医学效果验收。

## 工作区审计

| 范围 | 判定与处理 |
| --- | --- |
| `personal_assistant_manager.py`、协作测试 | 延续此前确认的 Triage 汇总多领域请求、专员不相互转交、区分新闻模型拒绝与新闻 API 失败；审计后运行离线回归并单独提交，不宣称验证了真实新闻服务 |
| `启动Aide.ps1`、根 README | 原有修改增加模型端口探测；本次保留其意图，补进程归属、重复启动保护、地址报告、健康检查与 MCP 所有权 |
| `ui/src/TestApp.tsx`、`main-test.tsx`、两个性能工具 | 没有被正式入口引用；保留文件，不删除、不宣称已修好。正式 tsconfig 明确排除，实验配置独立检查。正式代码若导入这些文件，TypeScript 仍会检查它们 |
| `ui/index-test.html`、`PERFORMANCE_OPTIMIZATION.md`、根 package 文件 | 本地实验配套，未作为正式应用依赖提交；正式前端依赖仍由 `ui/package*.json` 管理 |
| `backend/simple_server.py` | 简易独立试验服务，不等于 Aide 后端，不纳入正式启动流程 |
| `.claude/`、`.fastmcp/` | 本地工具配置/缓存，保留，不随本次提交上传 |

因此本轮交付后，工作区仍可能存在这些未跟踪实验文件；不是遗漏提交，也不能声称它们已验收。

## 本地启动

```powershell
.\启动Aide.ps1
.\启动Aide.ps1 -Status
.\启动Aide.ps1 -AllowOffline
.\scripts\test-aide-runtime.ps1
```

- 根据 Python/Node 可执行路径及本项目命令行识别归属，不按进程名直接杀进程。
- 后端固定 8000、MCP 固定 8002。非本项目占用时失败并显示 PID；不修改其他应用。
- 已运行的前端优先复用，否则从指定前端端口起尝试 11 个端口，使用 Vite `--strictPort` 防止悄悄漂移。
- 同一目录的启动脚本使用互斥锁；日志按时间保存；输出真实 URL/PID，并写 `logs/aide-runtime.json`。状态文件是最近检查快照，`-Status` 才是当前进程查询。
- 新建服务前做模型 TCP 探测，不携带密钥，不发送问答。不支持将此探测解释为模型调用成功；代理型环境可能需要 `-AllowOffline` 启动后另验模型。
- 先等待 MCP 监听，再启动 API；API 使用 `AIDE_EXTERNAL_MCP=true` 时不再生成或管理第二个 MCP 子进程。API 通过数据库健康检查后才报告就绪。
- 监听/健康失败时明确报错并保留已启动进程供检查；不会自动清理其他进程。直接 uvicorn 启动保留原内部 MCP 流程，不能与脚本同时启动第二个 API。
- 不自动重启已运行服务以更新代码；变更 Python 代码后的重启仍需针对已核对的本项目进程操作。

## 构建与验证入口

```powershell
cd ui
npm ci
npm run typecheck
npm run build
# 仅检查本机保留的实验文件，仍可能失败；不属于正式应用通过承诺
npm run typecheck:experiments

cd ../backend
.\.venv\python.exe -m unittest tests.test_agent_coordination tests.test_external_mcp tests.test_note_local_search tests.test_medical_grounding tests.test_answer_audit
```

本轮使用已有安装完成：正式 TypeScript 检查通过、Vite 生产构建通过、12 项脚本端口/归属测试通过、26 项后端回归通过。测试中的 LiteLLM 价格表下载受到网络限制后使用包内备份，未调用收费生成接口。仍有既有 Pydantic 弃用、Browserslist 数据过期和混合导入构建警告。

实际启动先成功复用 MCP/API/UI；随后仅重启已核对属于本项目的 API，MCP 与 UI 的 PID 保持不变，API 日志确认使用外部 MCP，数据库健康通过。页面复验可打开，显示“已连接 admin”。旧浏览器页的自动化连接曾超时，改用新页面完成复验；捕获到 3 条 WebSocket 错误事件后页面处于已连接状态，不能宣称控制台全程零错误。完整网络故障矩阵仍在后续阶段。

本轮没有在全新 Windows 主机上完成安装复现。模型文件、密钥、原始语料与个人数据库仍留在本机，不进入 Git。

## 后续仍需完成

10 月 1 日进展：已完成 100/1000 条合成笔记规模测试、60 题困难样例基线，以及三项受控索引故障测试。详见 `note-search-scale-validation.md`；真实故障矩阵、外部盲测及困难负例修复仍未完成。

1. 扩充真实表达与困难负例；固定开发/验证划分，保留已知失败。
2. 100/1000 条模拟库、并发写入、索引进程中断和实际网络故障测试。
3. 普通腹痛等可靠中文资料补充及回答语义依据检查。
4. 依据数据决定笔记 reranker、共享模型服务和更完整结构切片，不预先宣称收益。
