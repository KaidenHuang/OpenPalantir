"""content_extraction 单元测试 —— 转换器与章节树解析（纯解析，无 LLM、无外部服务）"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(BASE, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from content_extraction import extract_content, ExtractedDocument, Section          # noqa: E402
from content_extraction.converters import get_converter, supported_extensions       # noqa: E402
from content_extraction.md_parser import parse_markdown_sections, single_section    # noqa: E402


# ── 注册表 ──────────────────────────────────────────────────

def test_supported_extensions():
    from content_extraction.converters import supported_extensions
    exts = supported_extensions()
    for ext in (".pdf", ".docx", ".md", ".txt"):
        assert ext in exts
        assert get_converter(ext) is not None

def test_unsupported_extension():
    converter = get_converter(".pptx")
    assert converter is None
    with pytest.raises(ValueError):
        extract_content("不存在路径.pptx")


# ── Markdown 章节解析 ───────────────────────────────────────

def test_md_hierarchy_and_text():
    md = "# 主标题\n\n引言正文\n\n## 小节A\n\nA 的正文\n\n### 细节\n\n细节正文\n\n## 小节B\n\nB 的正文\n"
    sections = parse_markdown_sections([(None, md)])
    assert len(sections) == 1
    root = sections[0]
    assert root.title == "主标题"
    assert "引言正文" in root.text
    assert [c.title for c in root.children] == ["小节A", "小节B"]
    a = root.children[0]
    assert a.level == 2
    assert any(c.title == "细节" for c in a.children)
    # 正文归属：A 的正文在 A、细节正文在细节、B 的正文在 B，互不串
    assert "A 的正文" in a.text and "细节正文" not in a.text
    assert "细节正文" in a.children[0].text
    assert "B 的正文" in root.children[1].text


def test_md_preamble_before_first_heading():
    md = "文档开头的导语\n\n# 标题\n\n正文\n"
    sections = parse_markdown_sections([(None, md)])
    assert sections[0].title == "（开头）"
    assert "导语" in sections[0].text
    # 随后的 H1 是同一层级，与「开头」并列
    assert [c.title for c in sections[0].children] == []
    assert len(sections) == 2 and sections[1].title == "标题"


def test_md_code_fence_not_parsed_as_heading():
    md = "## 小节\n\n```python\n# 这不是标题\n```\n\n后续\n"
    sections = parse_markdown_sections([(None, md)])
    assert len(sections) == 1
    assert "# 这不是标题" in sections[0].text


def test_md_page_anchor():
    pages = [(0, "# 首页标题\n\n首页正文\n"), (1, "跨页正文\n"), (2, "# 次页标题\n\n次页正文\n")]
    sections = parse_markdown_sections(pages)
    assert sections[0].page_start == 1 and sections[0].page_end == 2
    assert sections[1].page_start == 3 and sections[1].page_end == 3


def test_single_section_fallback():
    sections = single_section("doc", "全部正文")
    assert sections[0].title == "doc"
    assert "全部正文" in sections[0].text


# ── TXT / DOCX ─────────────────────────────────────────────

def test_txt_converter(tmp_path):
    p = tmp_path / "sample.txt"
    p.write_text("第一段\n\n第二段", encoding="utf-8")
    ex = extract_content(str(p))
    assert ex.format == "txt"
    assert ex.page_count is None
    assert len(ex.sections) == 1
    assert "第二段" in ex.sections[0].text


def _make_docx(tmp_path, body: str):
    from docx import Document

    doc = Document()
    doc.add_heading("文档标题", level=1)
    doc.add_paragraph("导语段落")
    doc.add_heading("方案一", level=2)
    doc.add_paragraph(body)
    doc.add_heading("方案二", level=2)
    doc.add_paragraph("方案二正文")
    p = tmp_path / "sample.docx"
    doc.save(str(p))
    return str(p)


def test_docx_converter(tmp_path):
    path = _make_docx(tmp_path, "方案一正文")
    ex = extract_content(path)
    assert ex.format == "docx"
    assert [s.title for s in ex.sections] == ["文档标题"]
    root = ex.sections[0]
    assert "导语段落" in root.text
    assert [c.title for c in root.children] == ["方案一", "方案二"]
    assert "方案一正文" in root.children[0].text


def test_docx_table_content(tmp_path):
    from docx import Document

    doc = Document()
    doc.add_heading("标题", level=1)
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "姓名"
    table.rows[0].cells[1].text = "部门"
    p = tmp_path / "with_table.docx"
    doc.save(str(p))
    ex = extract_content(str(p))
    assert "姓名" in ex.sections[0].text and "部门" in ex.sections[0].text


def test_docx_empty_raises(tmp_path):
    from docx import Document

    p = tmp_path / "empty.docx"
    Document().save(str(p))
    with pytest.raises(ValueError):
        extract_content(str(p))


# ── PDF（需要样例文件，找不到则跳过）──────────────────────

PDF_SAMPLE = r"E:\产品资料\技术方案文档\CDM技术资料\ESSS拓展分布式架构相关资料\ASU与AnyBackup CDM整合技术可行性探讨资料\Cohesity-SpanFS-and-SnapTree-WP.pdf"


@pytest.mark.integration
@pytest.mark.skipif(not os.path.isfile(PDF_SAMPLE), reason="本地样例 PDF 不存在")
def test_pdf_page_anchor():
    ex = extract_content(PDF_SAMPLE)
    assert ex.format == "pdf"
    assert ex.page_count and ex.page_count > 0
    assert ex.sections
    for root in ex.sections:
        assert root.page_start is not None
