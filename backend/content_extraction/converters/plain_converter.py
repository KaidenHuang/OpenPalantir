"""MD/TXT 转换器 —— 原文直接进 Markdown 解析器，无页码锚点"""
import os

from ..models import ExtractedDocument
from ..md_parser import parse_markdown_sections, single_section


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def extract_md(path: str) -> ExtractedDocument:
    text = _read_text(path)
    doc_name = os.path.splitext(os.path.basename(path))[0]
    sections = parse_markdown_sections([(None, text)])
    if not sections:
        sections = single_section(doc_name, text)
    return ExtractedDocument(doc_name=doc_name, format="md", page_count=None, sections=sections)


def extract_txt(path: str) -> ExtractedDocument:
    text = _read_text(path)
    doc_name = os.path.splitext(os.path.basename(path))[0]
    sections = single_section(doc_name, text)
    return ExtractedDocument(doc_name=doc_name, format="txt", page_count=None, sections=sections)
