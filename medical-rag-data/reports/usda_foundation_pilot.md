# USDA Foundation Foods 结构化数据试点

日期：2026-09-24。数据来自 [USDA FoodData Central 下载页](https://fdc.nal.usda.gov/download-datasets/)的 2026-04-30 Foundation Foods JSON。使用条件见 [官方 API 与数据说明](https://fdc.nal.usda.gov/api-guide/)；营养量以每 100 克食物计，参见 [Foundation Foods 文档](https://fdc.nal.usda.gov/Foundation_Foods_Documentation/)。

## 复现

在 `backend` 目录运行：

```powershell
.\.venv\python.exe -m medical.download_usda_foundation
.\.venv\python.exe -m medical.import_usda_foundation
.\.venv\python.exe -m medical.export_usda_graph
```

下载的 ZIP 和生成的 SQLite 数据库不入库。导入器校验固定的 ZIP 与 JSON SHA256，并写入三个 SQLite 表：`foods`、`nutrients`、`food_nutrients`。版本、校验值和数量记录在 `structured/usda_foundation_2026-04-30_manifest.json`。

## 导入结果

原始 JSON 有 395 个数组位置，其中 32 个为空。实际导入 363 种食物、228 项营养素定义和 15,193 条食物营养值；其中 27 条缺少数值，保留为空值。图谱导出包含食物、营养素节点及 15,193 条带数值和来源的 `HAS_NUTRIENT` 边。

这是离线数据试点，`agent_enabled=false`。原始数据以美国食品为主，尚无经过核对的中文食物名称映射，也没有食物与药物相互作用关系；当前医疗 Agent 不会据此生成饮食或用药建议。
