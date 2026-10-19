"""DOCX 转换器 —— python-docx：标题样式（Title/Heading N）映射到章节层级"""
import os
from typing import Optional

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from system.logger import logger
from ..models import ExtractedDocument, Section

# Word 样式名 → 标题层级（Title 视作一级，Heading N → N）
_HEADING_STYLES = {"title": 1}


def _heading_level(style_name: str) -> Optional[int]:
    """Word 样式名 → 标题层级；非标题样式返回 None"""
    name = (style_name or "").strip().lower()
    if name in _HEADING_STYLES:
        return _HEADING_STYLES[name]
    if name.startswith("heading"):
        _, _, num = name.partition(" ")
        try:
            level = int(num)
        except (ValueError, TypeError):
            return None
        return min(level, 6) if level >= 1 else None
    return None


def _iter_blocks(doc):
    """按文档物理顺序产出段落与表格（保持正文流，不丢表格内容）"""
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _table_text(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def extract_docx(path: str) -> ExtractedDocument:
    doc = Document(path)
    doc_name = os.path.splitext(os.path.basename(path))[0]

    roots: list = []
    stack: list = []

    def append_text(text: str):
        if not text:
            return
        if not stack:
            # 首标题之前的正文挂到隐式「开头」章节
            root = Section(title="（开头）", level=1)
            roots.insert(0, root)
            stack.append(root)
        node = stack[-1]
        node.text = f"{node.text}\n{text}" if node.text else text

    for block in _iter_blocks(doc):
        if isinstance(block, Table):
            append_text(_table_text(block))
            continue
        style_name = block.style.name if block.style is not None else ""
        level = _heading_level(style_name)
        title = block.text.strip()
        if level and title:
            node = Section(title=title, level=level)
            while stack and stack[-1].level >= level:
                stack.pop()
            if stack:
                stack[-1].children.append(node)
            else:
                roots.append(node)
            stack.append(node)
        else:
            append_text(title)

    full_text = "\n".join(p.text for p in doc.paragraphs).strip()
    if not full_text:
        raise ValueError("DOCX 无可提取的文本内容")
    if not roots:
        # 无任何标题样式的文档：整篇作为单章节（旧管线 fallback_text 语义）
        logger.warning(f"[docx_converter] 无标题样式，整篇作为单章节: {doc_name}")
        roots = [Section(title=doc_name, level=1, text=full_text)]

    return ExtractedDocument(doc_name=doc_name, format="docx", page_count=None, sections=roots)
