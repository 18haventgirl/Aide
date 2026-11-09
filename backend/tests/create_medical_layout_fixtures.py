"""Create reproducible, fictional table/handwriting layout samples.

Usage: python backend/tests/create_medical_layout_fixtures.py
Requires Pillow, python-docx, reportlab and Windows CJK fonts.
The blue handwriting and signature are synthetic visual marks, not clinical facts.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "backend" / "tests" / "fixtures" / "medical-layout"

IDENTITY = [
    ("姓名", "周示例", "性别", "女"),
    ("年龄", "38岁", "科室", "全科门诊"),
    ("就诊日期", "2026-10-09", "过敏史", "青霉素过敏"),
]
VISIT = [
    ("主诉", "咳嗽3天"),
    ("现病史", "干咳3天，否认胸痛，无发热。"),
    ("既往史", "否认高血压病史。"),
    ("初步诊断", "上呼吸道感染（待排）。"),
    ("处理", "本次未开药。"),
    ("医嘱", "观察症状变化，必要时复诊。"),
]


def make_docx(path: Path) -> None:
    from docx import Document
    from docx.shared import Cm, Pt

    document = Document()
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Cm(1.8)
    document.add_heading("虚构测试病历 · 表格版", level=1)
    document.add_paragraph("示例医院 / 门诊记录 / 不是真实患者资料")
    table = document.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    for cell, value in zip(table.rows[0].cells, ("项目", "记录", "项目", "记录")):
        cell.text = value
    for row in IDENTITY:
        for cell, value in zip(table.add_row().cells, row):
            cell.text = value
    document.add_heading("就诊信息", level=2)
    visit = document.add_table(rows=1, cols=2)
    visit.style = "Table Grid"
    visit.rows[0].cells[0].text = "项目"
    visit.rows[0].cells[1].text = "记录"
    for key, value in VISIT:
        cells = visit.add_row().cells
        cells[0].text = key
        cells[1].text = value
    document.add_paragraph("核对提示：本文件仅有文字表格，没有签名图片。")
    document.styles["Normal"].font.size = Pt(11)
    document.save(path)


def make_native_pdf(path: Path) -> None:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    pdf = canvas.Canvas(str(path), pagesize=(595, 842))
    pdf.setTitle("虚构测试病历 - 表格版")
    pdf.setFont("STSong-Light", 18)
    pdf.drawString(45, 790, "虚构测试病历 · 表格版")
    pdf.setFont("STSong-Light", 10)
    pdf.drawString(45, 765, "示例医院 / 门诊记录 / 不是真实患者资料")

    def table(top: int, widths: list[int], rows: list[tuple[str, ...]], row_height: int = 32) -> int:
        left = 45
        bottom = top - row_height * len(rows)
        pdf.setStrokeColorRGB(0.72, 0.77, 0.82)
        for i in range(len(rows) + 1):
            y = top - i * row_height
            pdf.line(left, y, left + sum(widths), y)
        x = left
        for width in [0] + widths:
            if width:
                x += width
            pdf.line(x, top, x, bottom)
        pdf.setFont("STSong-Light", 11)
        for row_index, row in enumerate(rows):
            x = left
            for value, width in zip(row, widths):
                pdf.drawString(x + 8, top - row_height * row_index - 21, value)
                x += width
        return bottom

    y = table(740, [75, 170, 75, 185], [("项目", "记录", "项目", "记录"), *IDENTITY])
    pdf.setFont("STSong-Light", 14)
    pdf.drawString(45, y - 40, "就诊信息")
    table(y - 55, [100, 405], [("项目", "记录"), *VISIT], 37)
    pdf.setFont("STSong-Light", 9)
    pdf.drawString(45, 45, "仅用于表格读取与原文预览测试；无真实患者信息。")
    pdf.save()


def make_scan(image_path: Path, pdf_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1800, 2380), "#fbfbf8")
    draw = ImageDraw.Draw(image)
    sans = "C:/Windows/Fonts/msyh.ttc"
    handwritten = "C:/Windows/Fonts/simkai.ttf"
    font = ImageFont.truetype(sans, 40)
    bold = ImageFont.truetype(sans, 54)
    small = ImageFont.truetype(sans, 29)
    hand = ImageFont.truetype(handwritten, 48)
    ink, grid, blue = "#263346", "#a8b5c4", "#315d9b"
    draw.text((100, 92), "虚构测试病历 · 扫描版", font=bold, fill=ink)
    draw.text((100, 175), "示例医院 / 门诊记录 / 不是真实患者资料", font=small, fill="#5b6777")

    def row(y: int, cells: list[str], bounds: list[int], height: int = 100) -> None:
        for x in bounds:
            draw.line((x, y, x, y + height), fill=grid, width=3)
        draw.line((bounds[0], y, bounds[-1], y), fill=grid, width=3)
        draw.line((bounds[0], y + height, bounds[-1], y + height), fill=grid, width=3)
        for index, value in enumerate(cells):
            draw.text((bounds[index] + 16, y + 24), value, font=font, fill=ink)

    bounds4 = [100, 325, 905, 1130, 1700]
    row(270, ["项目", "记录", "项目", "记录"], bounds4)
    for index, values in enumerate(IDENTITY, 1):
        row(270 + index * 100, list(values), bounds4)
    draw.text((100, 720), "就诊信息", font=bold, fill=ink)
    bounds2 = [100, 420, 1700]
    row(810, ["项目", "记录"], bounds2)
    for index, (key, value) in enumerate(VISIT, 1):
        row(810 + index * 100, [key, value], bounds2)

    draw.text((100, 1580), "手写备注（模拟）", font=bold, fill=ink)
    draw.rounded_rectangle((100, 1670, 1700, 2050), radius=12, outline=grid, width=3)
    draw.line((170, 1810, 1610, 1810), fill="#d1d9e2", width=2)
    draw.line((170, 1935, 1610, 1935), fill="#d1d9e2", width=2)
    draw.text((185, 1715), "复查体温，关注咳嗽变化。", font=hand, fill=blue)
    draw.text((950, 1850), "周示例（模拟签名）", font=hand, fill=blue)
    draw.line([(1330, 1910), (1400, 1890), (1460, 1920), (1530, 1880), (1620, 1905)], fill=blue, width=4, joint="curve")
    draw.text((100, 2140), "手写区域仅用于观察 OCR 与原件预览，不作为自动提取的可信字段。", font=small, fill="#5b6777")
    image.save(image_path, format="PNG", optimize=True)
    image.save(pdf_path, format="PDF", resolution=150.0)
    image.close()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    make_docx(OUTPUT / "fictional-table.docx")
    make_native_pdf(OUTPUT / "fictional-table.pdf")
    make_scan(OUTPUT / "fictional-handwritten-note.png", OUTPUT / "fictional-handwritten-note.pdf")
    manifest = {
        "disclaimer": "全为虚构资料，蓝色手写和签名仅为模拟视觉标记，不是真实患者或医护签名。",
        "facts_to_check": {"name": "周示例", "date": "2026-10-09", "allergy": "青霉素过敏", "diagnosis_qualifier": "待排", "negation": "否认胸痛"},
        "files": [
            {"name": "fictional-table.docx", "purpose": "DOCX 文字表格读取；页面展示为提取后的原文。"},
            {"name": "fictional-table.pdf", "purpose": "文字 PDF 表格读取和 PDF 原件预览。"},
            {"name": "fictional-handwritten-note.png", "purpose": "扫描表格 OCR、手写备注与模拟签名原件预览。"},
            {"name": "fictional-handwritten-note.pdf", "purpose": "扫描 PDF 表格 OCR、手写备注与模拟签名原件预览。"},
        ],
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Created {len(manifest['files'])} fictional fixtures in {OUTPUT}")


if __name__ == "__main__":
    main()
