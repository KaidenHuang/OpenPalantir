"""PDF 转换器 —— pymupdf4llm 按页转 Markdown，页码作为锚点写进章节"""
import os

from system.logger import logger
from ..models import ExtractedDocument
from ..md_parser import parse_markdown_sections, single_section


def extract_pdf(path: str) -> ExtractedDocument:
    import pymupdf4llm

    chunks = pymupdf4llm.to_markdown(path, page_chunks=True, show_progress=False)
    pages = []
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        page_number = metadata.get("page_number")   # 0-based
        pages.append((page_number, chunk.get("text", "")))

    doc_name = os.path.splitext(os.path.basename(path))[0]
    page_count = len(pages)
    sections = parse_markdown_sections(pages)

    full_text = "\n".join(c for _, c in pages).strip()
    if not full_text:
        raise ValueError("PDF 无法提取出文本（可能为扫描件/图片版 PDF，暂不支持）")
    if not sections:
        logger.warning(f"[pdf_converter] 未能识别出标题结构，整篇作为单章节: {doc_name}")
        sections = single_section(doc_name, full_text, page_count)

    return ExtractedDocument(doc_name=doc_name, format="pdf",
                             page_count=page_count, sections=sections)
