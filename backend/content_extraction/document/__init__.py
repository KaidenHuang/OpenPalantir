"""
内容提取（文档侧）—— 各格式文档 → 统一 ExtractedDocument（章节树 + 页码锚点）

本模块只做确定性解析（无 LLM）：标题层级、正文、页码全部来自
文档本身的样式/结构信息。摘要提取在 summary_generation.document 完成。

有章节结构的按章节分树，没有的按单一 Section（标题=文件名）分。
PDF 的表格转成与表格文件同一套「表档案」正文、插图落盘后按占位/OCR 文本替换，
但 PDF 表不建行实体（见 pdf_tables.py / pdf_images.py）。
表格文件（xlsx/xlsm/csv/tsv）的一个工作表 = 一个一级章节，正文是确定性表档案；
明细行经 `table_reader.iter_table_rows` 供 ④ 重读源文件时取用。
"""
import os
from typing import Optional

from .converters import get_converter, legacy_hint
from .models import ExtractedDocument, Section
from .table_reader import iter_table_rows


def extract_content(path: str, *, images_dir: Optional[str] = None) -> ExtractedDocument:
    """把文档提取为统一中间结构

    images_dir 只有 PDF 转换器消费（插图落盘目录），其余转换器忽略。

    Raises:
        ValueError: 不支持的文件类型 / 文档无可提取内容
    """
    ext = os.path.splitext(path)[1].lower()
    converter = get_converter(ext)
    if not converter:
        hint = legacy_hint(ext)
        if hint:
            raise ValueError(hint)
        raise ValueError(f"不支持的文件类型: {ext}")
    if ext == ".pdf":
        return converter(path, images_dir=images_dir)
    return converter(path)


__all__ = ["extract_content", "iter_table_rows", "ExtractedDocument", "Section"]
