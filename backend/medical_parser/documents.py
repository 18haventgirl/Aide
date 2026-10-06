"""Bounded text extraction; PDF text first, local OCR only when needed.

Pipeline design references KnowResume (Apache-2.0), revision 691f4140.
See docs/medical-record-parser.md for the reuse boundary and attribution.
"""

import io
import threading
import zipfile
from contextlib import closing
from pathlib import Path
from xml.etree import ElementTree

from .schema import MAX_BYTES, MAX_PAGES, MAX_TEXT, ParserError, SourceLine

_ocr_engine = None
_ocr_lock = threading.Lock()
SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".txt"}


def _lines(text: str, page: int, method: str) -> list[SourceLine]:
    return [SourceLine(id=f"p{page}-l{i + 1}", page=page, text=line.strip(), method=method)
            for i, line in enumerate(text.splitlines()) if line.strip()]


def _check(lines: list[SourceLine]) -> list[SourceLine]:
    size = sum(len(line.text) for line in lines)
    if size > MAX_TEXT:
        raise ParserError("文档文字超过 4 万字，请按一次就诊拆分后上传。", 413)
    if size < 10:
        raise ParserError("未读取到足够的病历文字，请上传清晰文件或粘贴文字。")
    return lines


def extract_text(text: str) -> list[SourceLine]:
    return _check(_lines(text, 1, "text"))


def _ocr(data: bytes, page: int) -> list[SourceLine]:
    global _ocr_engine
    try:
        from PIL import Image
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise ParserError("此文件需要 OCR。请先安装病历解析的 OCR 依赖，或改用文字版 PDF / 粘贴文字。", 503) from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 20_000_000:
                raise ParserError("图片超过 2000 万像素，请缩小后上传。", 413)
            image.verify()
        # RapidOCR owns reusable ONNX sessions. Serialize calls to the shared engine.
        with _ocr_lock:
            if _ocr_engine is None:
                _ocr_engine = RapidOCR()
            result, _ = _ocr_engine(data)
    except ParserError:
        raise
    except Exception as exc:
        raise ParserError("图片识别失败，请换用清晰的正向图片或粘贴病历文字。") from exc
    return [SourceLine(id=f"p{page}-l{i + 1}", page=page, text=str(row[1]),
                       method="ocr", confidence=float(row[2]))
            for i, row in enumerate(result or []) if str(row[1]).strip()]


def _pdf(data: bytes) -> list[SourceLine]:
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ParserError("请先解除 PDF 密码保护后再上传。")
        if len(reader.pages) > MAX_PAGES:
            raise ParserError("第一版支持最多 12 页，请按一次就诊拆分。", 413)
        lines = []
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text(extraction_mode="layout") or ""
            # Image-bearing pages also use OCR so scanned sections aren't silently omitted.
            has_images = bool(page.images)
            if len(text.strip()) >= 25 and "\ufffd" not in text and not has_images:
                lines.extend(_lines(text, number, "pdf"))
            else:
                try:
                    import pypdfium2 as pdfium
                except ImportError as exc:
                    raise ParserError("扫描或混合 PDF 需要 OCR 依赖，请安装后重试，或粘贴文字。", 503) from exc
                with closing(pdfium.PdfDocument(data)) as document:
                    pdf_page = document[number - 1]
                    width, height = pdf_page.get_size()
                    scale = min(2.0, (20_000_000 / max(width * height, 1)) ** 0.5)
                    bitmap = pdf_page.render(scale=scale)
                    image = bitmap.to_pil()
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    image.close()
                    bitmap.close()
                    pdf_page.close()
                    page_lines = _ocr(buffer.getvalue(), number)
                if not page_lines:
                    raise ParserError(f"第 {number} 页没有识别到文字，请检查页面或移除空白页。")
                lines.extend(page_lines)
            if sum(len(line.text) for line in lines) > MAX_TEXT:
                raise ParserError("文档文字超过 4 万字，请拆分。", 413)
        return lines
    except ParserError:
        raise
    except Exception as exc:
        raise ParserError("无法读取 PDF，请检查文件是否完整，或转换成清晰图片。") from exc


def _docx(data: bytes) -> list[SourceLine]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 500 or sum(item.file_size for item in entries) > 30 * 1024 * 1024:
                raise ParserError("Word 文档解压后过大，请拆分。", 413)
            if any(item.filename.startswith("word/media/") for item in entries):
                raise ParserError("此 Word 含嵌入图片，请导出为 PDF 后上传，避免遗漏图片中的病历。")
            xml = archive.read("word/document.xml")
            if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                raise ParserError("不支持此 Word 文档格式。")
            root = ElementTree.fromstring(xml)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            # Includes paragraphs inside tables in source order, without duplicate nested text.
            paragraphs = ["".join(node.text or "" for node in p.findall(".//w:t", ns))
                          for p in root.findall(".//w:p", ns)]
            return _lines("\n".join(paragraphs), 1, "docx")
    except ParserError:
        raise
    except Exception as exc:
        raise ParserError("无法读取 Word 文档，请保存为 .docx 或 PDF 后重试。") from exc


def extract_file(name: str, data: bytes) -> list[SourceLine]:
    if not data or len(data) > MAX_BYTES:
        raise ParserError("请选择非空文件，且大小不超过 10 MB。", 413)
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED:
        raise ParserError("支持 PDF、PNG、JPG、DOCX 和 UTF-8 TXT 文件。", 415)
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ParserError("文件内容不是有效的 PDF。")
        lines = _pdf(data)
    elif suffix == ".docx":
        lines = _docx(data)
    elif suffix == ".txt":
        try:
            lines = _lines(data.decode("utf-8-sig"), 1, "text")
        except UnicodeDecodeError as exc:
            raise ParserError("TXT 文件需要 UTF-8 编码，也可以直接粘贴文字。") from exc
    else:
        lines = _ocr(data, 1)
    return _check(lines)
