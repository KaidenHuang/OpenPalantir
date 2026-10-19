"""
内容提取（文档侧）—— 各格式文档 → 统一 ExtractedDocument（章节树 + 页码锚点）

本模块只做确定性解析（无 LLM）：标题层级、正文、页码全部来自
文档本身的样式/结构信息。摘要提取在 summary_generation.document 完成。

有章节结构的按章节分树，没有的按单一 Section（标题=文件名）分。
"""
import os

from .converters import get_converter
from .models import ExtractedDocument, Section


def extract_content(path: str) -> ExtractedDocument:
    """把文档提取为统一中间结构

    Raises:
        ValueError: 不支持的文件类型 / 文档无可提取内容
    """
    ext = os.path.splitext(path)[1].lower()
    converter = get_converter(ext)
    if not converter:
        raise ValueError(f"不支持的文件类型: {ext}")
    return converter(path)


__all__ = ["extract_content", "ExtractedDocument", "Section"]
