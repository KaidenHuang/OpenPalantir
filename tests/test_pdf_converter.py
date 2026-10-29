"""PDF 转换器集成冒烟 —— 现场生成 PDF 验证表格表档案、插图落盘、扫描件兜底

fixture 全部用 pymupdf 现场画，不往仓库里放二进制样例。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(BASE, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import pymupdf                                            # noqa: E402

from content_extraction.document import extract_content   # noqa: E402
from content_extraction.document import pdf_images        # noqa: E402

pytestmark = pytest.mark.unit


def _text(page, x, y, text, size=11):
    page.insert_text((x, y), text, fontsize=size, fontname="helv")


def _draw_table(page, left, top, widths, rows, row_h=26):
    total = sum(widths)
    x = left
    for width in widths:
        page.draw_line((x, top), (x, top + row_h * len(rows)))
        x += width
    page.draw_line((x, top), (x, top + row_h * len(rows)))
    for index in range(len(rows) + 1):
        y = top + index * row_h
        page.draw_line((left, y), (left + total, y))
    for r, row in enumerate(rows):
        x = left
        for c, cell in enumerate(row):
            _text(page, x + 6, top + r * row_h + 17, cell, size=10)
            x += widths[c]


ROWS = [["Region", "Q1", "Q2", "Q3"],
        ["North", "120", "135", "150"],
        ["South", "90", "95", "110"],
        ["West", "70", "88", "92"]]


def _table_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    _text(page, 72, 72, "Quarterly Sales Report", size=22)
    _text(page, 72, 120, "This section describes regional sales performance.")
    _draw_table(page, 72, 160, [110, 90, 90, 90], ROWS)
    doc.save(str(path))
    doc.close()
    return path


def _plain_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    _text(page, 72, 72, "Chapter One", size=20)
    _text(page, 72, 120, "Plain prose without any table structure at all.")
    doc.save(str(path))
    doc.close()
    return path


def _image_pdf(path, tmp_dir):
    block = tmp_dir / "block.png"
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 300), 0)
    pix.clear_with(180)
    pix.save(str(block))

    doc = pymupdf.open()
    page = doc.new_page()
    _text(page, 72, 72, "Figure Section", size=20)
    page.insert_image(pymupdf.Rect(80, 120, 420, 380), filename=str(block))
    _text(page, 80, 420, "Caption text below the figure.")
    doc.save(str(path))
    doc.close()
    return path


def _scanned_pdf(path, tmp_dir):
    source = pymupdf.open()
    page = source.new_page()
    _text(page, 72, 72, "Scanned Report", size=24)
    _text(page, 72, 120, "This page is a raster image, not text.")
    png = tmp_dir / "scan_page.png"
    page.get_pixmap(dpi=150).save(str(png))
    source.close()

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, filename=str(png))
    doc.save(str(path))
    doc.close()
    return path


# ── 表格 ────────────────────────────────────────────────────

def test_pdf_table_becomes_profile_text(tmp_path):
    ex = extract_content(str(_table_pdf(tmp_path / "table.pdf")))

    assert ex.format == "pdf"
    assert ex.page_count == 1
    assert not ex.sections[0].text.strip().startswith("|")
    assert "【工作表】第1页 表1" in ex.sections[0].text
    assert "Region(TEXT)" in ex.sections[0].text
    assert "（仅展示前 2 行，共 3 行）" in ex.sections[0].text

    tables = ex.meta["pdf_tables"]
    assert len(tables) == 1
    assert tables[0].columns == ["Region", "Q1", "Q2", "Q3"]
    assert tables[0].column_types == ["TEXT", "NUM", "NUM", "NUM"]
    assert tables[0].row_count == 3


def test_pdf_page_numbers_are_one_based(tmp_path):
    ex = extract_content(str(_table_pdf(tmp_path / "table.pdf")))
    for root in ex.sections:
        assert root.page_start == 1
        assert root.page_end == 1


def test_plain_pdf_has_no_tables(tmp_path):
    ex = extract_content(str(_plain_pdf(tmp_path / "plain.pdf")))
    assert ex.meta["pdf_tables"] == []
    assert "Plain prose" in ex.sections[0].text


def test_pdf_without_images_dir_creates_nothing(tmp_path):
    path = _image_pdf(tmp_path / "image.pdf", tmp_path)
    ex = extract_content(str(path))
    assert "Caption text below the figure" in ex.sections[0].text
    assert not any(name.endswith(".images") or name.endswith(".images.tmp")
                   for name in os.listdir(tmp_path))


# ── 插图 ────────────────────────────────────────────────────

def test_picture_is_written_and_referenced(tmp_path):
    path = _image_pdf(tmp_path / "image.pdf", tmp_path)
    images = tmp_path / "images" / "image.pdf.images"

    ex = extract_content(str(path), images_dir=str(images))

    files = sorted(os.listdir(images))
    assert files and files[0].endswith(".png")
    text = ex.sections[0].text
    assert f"![]({pdf_images.public_ref(os.path.join(str(images), files[0]))})" in text
    assert "Caption text below the figure" in text


def test_regeneration_replaces_whole_image_dir(tmp_path):
    path = _image_pdf(tmp_path / "image.pdf", tmp_path)
    images = tmp_path / "images" / "image.pdf.images"

    extract_content(str(path), images_dir=str(images))
    stale = images / "stale.png"
    stale.write_bytes(b"old")

    extract_content(str(path), images_dir=str(images))

    assert not stale.exists()
    assert os.path.isfile(images / os.listdir(images)[0])


# ── 扫描件 ──────────────────────────────────────────────────

def test_scanned_pdf_requires_tesseract(tmp_path, monkeypatch):
    path = _scanned_pdf(tmp_path / "scan.pdf", tmp_path)
    monkeypatch.setattr(pdf_images, "_ocr_available_cache", False)

    with pytest.raises(ValueError, match="Tesseract"):
        extract_content(str(path), images_dir=str(tmp_path / "images" / "scan.pdf.images"))

    assert not os.path.isdir(tmp_path / "images" / "scan.pdf.images")
    assert not os.path.isdir(tmp_path / "images" / "scan.pdf.images.tmp")


@pytest.mark.skipif(not pdf_images.ocr_available(), reason="本机未安装 tesseract")
def test_scanned_pdf_uses_full_page_ocr(tmp_path):
    path = _scanned_pdf(tmp_path / "scan.pdf", tmp_path)
    ex = extract_content(str(path))
    assert ex.sections
    assert "Scanned" in "".join(section.text for section in ex.sections)


def test_short_text_pdf_is_not_treated_as_scanned(tmp_path, monkeypatch):
    """字符数少但确实有文字：没装 OCR 也不能报错，保留原文本"""
    monkeypatch.setattr(pdf_images, "_ocr_available_cache", False)
    doc = pymupdf.open()
    page = doc.new_page()
    _text(page, 72, 72, "Short note.")
    path = tmp_path / "short.pdf"
    doc.save(str(path))
    doc.close()

    ex = extract_content(str(path))
    assert "Short note" in ex.sections[0].text
