# Aide 前端工作台

工作台包含聊天、病历解析和个人数据页面。以下命令在 `ui/` 目录执行，已验证的 Node.js 版本为 24.19.0。

| 命令 | 用途 |
| --- | --- |
| `npm ci` | 按锁文件安装依赖 |
| `npm run dev` | 启动前端，访问终端输出的地址 |
| `npm run check` | 检查代码规范、类型并运行前端回归测试 |
| `npm run build` | 将生产版本及 PDF 预览资源构建到 `dist/` |
| `npm run test:api` | 使用演示账号连接本机预览服务，需要先设置下述联调参数 |

前端通过同站点的 `/api` 和 `/ws` 访问后端。Windows 用户可从项目根目录运行 `启动Aide.ps1` 一起启动 API、MCP 和前端，详见[项目启动指南](../README.md)。

联调前请设置 `AIDE_SMOKE_BASE_URL`（本机前端地址）、`AIDE_SMOKE_USERNAME` 和 `AIDE_SMOKE_PASSWORD`。验证聊天连接时还需设置 `AIDE_SMOKE_WS=1`。未设置地址时，联调套件会显示跳过。命令示例和最近一次通过的场景见[前端验证记录](../docs/frontend-quality-validation-20261102.md)。

手动试传 PDF 或图片时，可按[病历测试样例生成步骤](../docs/medical-record-parser.md#验证与边界)生成虚构文件，再从“病历解析”页面上传。例如，`matrix-20261009-scanned.pdf` 和 `matrix-20261009.png` 分别用于检查扫描 PDF 和图片的 OCR 及原件预览。
