# 病历版式测试样例

本目录包含虚构门诊病历，不包含真实患者资料。使用 `python backend/tests/create_medical_layout_fixtures.py` 可重新生成。

| 文件 | 主要检查点 |
| --- | --- |
| `fictional-table.docx` | Word 文字表格的顺序、原文提取。 |
| `fictional-table.pdf` | 文字 PDF 表格的提取与原件预览。 |
| `fictional-handwritten-note.png` | 图片表格 OCR、手写区域与签名位置的原件预览。 |
| `fictional-handwritten-note.pdf` | 扫描 PDF 的同一版面与预览。 |

上传后先核对姓名、就诊日期、过敏史、诊断中的“待排”，以及“否认胸痛”。手写备注和签名是**模拟视觉标记**，不能当作可靠的自动识别字段。当前解析器会把表格按文字行提取，不会保留单元格结构；DOCX 无原件版式预览。带签名图片的 DOCX 会被拒绝，请使用 PDF 或图片样例检查此场景。需要测试真实手写识别质量时，应另用获得授权并完成脱敏的样本。
