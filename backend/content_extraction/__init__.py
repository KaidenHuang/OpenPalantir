"""
内容提取模块 —— 各格式文档 → 统一 ExtractedDocument（章节树 + 页码锚点）

本模块只做确定性解析（无 LLM）：标题层级、正文、页码全部来自
文档本身的样式/结构信息。摘要提取在 content_summarization 模块完成。

新增格式（图片、PPT、音频、视频）时在 converters/ 注册表登记即可。
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
