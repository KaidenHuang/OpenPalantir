"""PDF 转换器 —— layout(GNN) 按页转 Markdown，表格转表档案、插图落盘

依赖 pymupdf4llm 1.28.x 的 layout 路径与内部 `parse_document` 参数集：
表格来自 GNN 表格框（与它渲染出的 Markdown 表同源，可精确替换），GNN 页内零表时
才用 `page.find_tables()` 兜底；插图经 `write_images/image_path` 落盘后按占位或 OCR
文本替换。layout 路径不支持的 image_size_limit/graphics_limit/table_strategy 不再传。

升级 pymupdf4llm 小版本前必须复核这些参数语义与 ParsedDocument 结构；
内部接口不可用时回退到公开的 to_markdown，只保留纯文本表格。
"""
import os
import re
import shutil
from typing import Any, Dict, List, Optional, Set, Tuple

from system.logger import logger
from .. import pdf_images
from ..md_parser import parse_markdown_sections, single_section
from ..models import ExtractedDocument
from ..pdf_tables import (
    MAX_PDF_TABLES,
    merge_continuations,
    replace_tables,
    tables_from_find_tables,
    tables_from_layout_page,
)

_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def extract_pdf(path: str, *, images_dir: Optional[str] = None) -> ExtractedDocument:
    import pymupdf

    settings = pdf_images.image_settings()
    if settings.mode == pdf_images.MODE_OCR and not pdf_images.ocr_available():
        logger.warning("[pdf_converter] DOC_IMAGE_MODE=ocr 但未检测到 tesseract，降级为 placeholder")
        settings = pdf_images.ImageSettings(
            mode=pdf_images.MODE_PLACEHOLDER, lang=settings.lang, enabled=settings.enabled)

    doc_name = os.path.splitext(os.path.basename(path))[0]
    doc = pymupdf.open(path)
    page_count = doc.page_count

    final_dir = images_dir if (images_dir and settings.enabled) else None
    tmp_dir = f"{final_dir}.tmp" if final_dir else None
    write_images = tmp_dir is not None
    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    success = False
    used_images: Set[str] = set()
    try:
        chunks, parsed = _parse(doc, path, tmp_dir, write_images)
        # 扫描件判定看的是「正文有多长」：图片引用（![](...)）不算文字，
        # 否则一整页扫描图会因为长路径被算成有内容
        raw_full_text = _IMAGE_REF_RE.sub(
            "", "\n".join(chunk.get("text", "") for chunk in chunks)).strip()
        page_texts, tables_by_page, used_images, skipped = _annotate_pages(
            doc, chunks, parsed, tmp_dir, final_dir, settings, write_images)

        all_tables = [table for tables in tables_by_page for table in tables]
        merged, candidates = merge_continuations(all_tables)
        if candidates:
            logger.info(f"[pdf_converter] 疑似续表但列名不一致 {len(candidates)} 处: {doc_name}")

        for index, (page_number, text) in enumerate(page_texts):
            page_tables = tables_by_page[index]
            if not page_tables:
                continue
            try:
                page_texts[index] = (page_number, replace_tables(text, page_tables)[0])
            except Exception as exc:
                logger.warning(f"[pdf_converter] 第 {page_number} 页表格替换失败，保留原文: {exc}")

        pages = [(page_number - 1, text) for page_number, text in page_texts]
        full_text = "\n".join(text for _, text in page_texts).strip()

        if pdf_images.is_scanned(raw_full_text, page_count):
            logger.warning(f"[pdf_converter] 文字版提取为空/过少，启用整页 OCR: {doc_name}")
            try:
                if not pdf_images.ocr_available():
                    raise ValueError(pdf_images.SCAN_ERROR)
                pages, full_text = _ocr_scanned(doc, settings.lang)
                used_images = set()
            except ValueError:
                # 有一点点文字（短文档）就别硬失败，OCR 只是补充手段
                if not raw_full_text.strip():
                    raise
                logger.warning("[pdf_converter] OCR 不可用或无结果，保留已提取的少量文本")

        if not pages:
            raise ValueError(pdf_images.SCAN_ERROR)
        sections = parse_markdown_sections(pages)
        if not sections:
            logger.warning(f"[pdf_converter] 未能识别出标题结构，整篇作为单章节: {doc_name}")
            sections = single_section(doc_name, full_text, page_count)

        success = True
        return ExtractedDocument(
            doc_name=doc_name, format="pdf", page_count=page_count, sections=sections,
            meta={"pdf_tables": [table.sheet for table in merged],
                  "potential_continuations": candidates,
                  "skipped_tables": skipped},
        )
    finally:
        doc.close()
        _finalize_images(tmp_dir, final_dir, used_images, success)


def _parse(doc, path: str, tmp_dir: Optional[str], write_images: bool):
    """优先 layout 内部接口（能拿到表格框结构）；不可用时回退公开 to_markdown"""
    try:
        from pymupdf4llm.helpers.document_layout import parse_document

        parsed = parse_document(
            doc,
            image_dpi=pdf_images.IMAGE_DPI,
            image_format="png",
            image_path=tmp_dir or "",
            write_images=write_images,
            show_progress=False,
            force_text=True,
            use_ocr=False,
            force_ocr=False,
        )
        chunks = parsed.to_markdown(page_chunks=True, write_images=write_images)
        return chunks, parsed
    except (ImportError, TypeError, AttributeError) as exc:
        logger.warning(f"[pdf_converter] layout 内部接口不可用，回退纯 Markdown: {exc}")
        import pymupdf4llm

        chunks = pymupdf4llm.to_markdown(path, page_chunks=True, show_progress=False)
        return chunks, None


def _annotate_pages(doc, chunks: List[Dict[str, Any]], parsed,
                    tmp_dir: Optional[str], final_dir: Optional[str],
                    settings: pdf_images.ImageSettings,
                    write_images: bool) -> Tuple[List[Tuple[int, str]], List[List[Any]], Set[str], int]:
    """逐页：图片替换 + 收集表格（不在这一步替换表，等跨页合并完成后再替换）"""
    page_texts: List[Tuple[int, str]] = []
    tables_by_page: List[List[Any]] = []
    used_images: Set[str] = set()
    skipped = 0

    for index, chunk in enumerate(chunks):
        text = chunk.get("text", "")
        if parsed is None:
            metadata = chunk.get("metadata") or {}
            page_number = int(metadata.get("page_number") or index + 1)
            page_texts.append((page_number, text))
            tables_by_page.append([])
            continue

        page_layout = parsed.pages[index]
        page_number = page_layout.page_number
        page_tables: List[Any] = []
        try:
            page_tables = tables_from_layout_page(page_layout, page_number)
            if not page_tables:
                page_tables = tables_from_find_tables(doc[index], page_number)
        except Exception as exc:
            logger.warning(f"[pdf_converter] 第 {page_number} 页表格识别失败: {exc}")

        remaining = MAX_PDF_TABLES - sum(len(tables) for tables in tables_by_page)
        if remaining <= 0:
            skipped += len(page_tables)
            page_tables = []
        elif len(page_tables) > remaining:
            skipped += len(page_tables) - remaining
            page_tables = page_tables[:remaining]

        if write_images:
            try:
                text, page_used = _replace_images(
                    text, page_layout, tmp_dir, final_dir, settings)
                used_images.update(page_used)
            except Exception as exc:
                logger.warning(f"[pdf_converter] 第 {page_number} 页图片处理失败: {exc}")

        page_texts.append((page_number, text))
        tables_by_page.append(page_tables)

    return page_texts, tables_by_page, used_images, skipped


def _replace_images(text: str, page_layout, tmp_dir: Optional[str],
                    final_dir: Optional[str], settings: pdf_images.ImageSettings) -> Tuple[str, Set[str]]:
    """把库生成的 ![](md_ref) 换成占位/OCR 文本，返回被引用的图片文件名"""
    used: Set[str] = set()
    for box_index, box in enumerate(page_layout.boxes):
        if box.boxclass not in ("picture", "formula"):
            continue
        image_ref = getattr(box, "image", None)
        if not isinstance(image_ref, str):
            continue
        old = "\n![](%s)\n" % image_ref
        if old not in text:
            logger.warning(f"[pdf_converter] 图片引用未命中: 第 {page_layout.page_number} 页 框 {box_index}")
            continue
        image_file = pdf_images.find_image_file(tmp_dir, page_layout.page_number, box_index)
        final_file = (os.path.join(final_dir, os.path.basename(image_file))
                      if image_file and final_dir else None)
        replacement = pdf_images.image_replacement(
            box.boxclass, pdf_images.area_ratio(box, page_layout),
            image_file, final_file, settings)
        text = text.replace(old, "\n" + replacement + "\n", 1)
        if final_file and replacement.startswith("![]"):
            used.add(os.path.basename(final_file))
    return text, used


def _ocr_scanned(doc, lang: str) -> Tuple[List[Tuple[int, str]], str]:
    """扫描件兜底：整篇逐页 OCR；OCR 不可用或识别仍为空时给可操作的错误"""
    if not pdf_images.ocr_available():
        raise ValueError(pdf_images.SCAN_ERROR)
    texts = pdf_images.ocr_pdf_pages(doc, lang)
    pages = [(index, text) for index, text in enumerate(texts) if text.strip()]
    full_text = "\n".join(text for _, text in pages).strip()
    if not full_text:
        raise ValueError(pdf_images.SCAN_ERROR)
    return pages, full_text


def _finalize_images(tmp_dir: Optional[str], final_dir: Optional[str],
                     used_images: Set[str], success: bool) -> None:
    """成功才动最终目录：清未引用图片 → 整目录原子替换；失败只清 tmp，旧图保持原样"""
    if not tmp_dir or not final_dir:
        return
    if not success:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return
    if not os.path.isdir(tmp_dir):
        if os.path.isdir(final_dir):
            shutil.rmtree(final_dir)
        return
    for name in os.listdir(tmp_dir):
        path = os.path.join(tmp_dir, name)
        if os.path.isfile(path) and name not in used_images:
            os.remove(path)
    if os.path.isdir(final_dir):
        shutil.rmtree(final_dir)
    os.makedirs(os.path.dirname(final_dir), exist_ok=True)
    os.replace(tmp_dir, final_dir)
