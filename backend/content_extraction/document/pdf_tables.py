"""PDF 表格 —— 从 layout 表格框转成与 xlsx 相同的表档案，并替换页内 Markdown

PDF 表格是「知识」不是「数据」：只替换成表档案文本进章节正文，供 ③/④ 的
prose 通道消费；不造行实体、不接 table_reader 的行读取（PDF 表无法按页+序号
可靠重定位源文件）。

表格来源优先用 layout(GNN) 的表格框，它与 pymupdf4llm 渲染出的 Markdown 表
同源，可以按原字符串精确替换；某页 GNN 一个表都没识别出来时，才用
`page.find_tables()` 兜底（结果追加到页尾，没有可替换的 Markdown 块）。
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .table_model import (
    PREVIEW_ROWS,
    SheetTable,
    column_names,
    detect_header,
    fit_row,
    infer_column_type,
    render_cell,
    render_profile,
)

logger = logging.getLogger(__name__)

MAX_PDF_TABLES = 20        # 单文档表数上限，超出记 skipped
MIN_TABLE_CELLS = 4        # 少于 4 个非空单元格视为布局残留
MIN_ROW_FILLED = 2         # 数据行至少 2 个非空单元格，否则视为垃圾行
CONTINUATION_TOP_PT = 40   # 表顶距页顶 < 40pt 视为候选续表

SOURCE_GNN = "gnn"
SOURCE_LINES = "lines"


@dataclass
class PdfTable:
    """PDF 中识别到的一个表：表档案 + 跨页合并所需的最小结构"""

    sheet: SheetTable
    page_start: int
    page_end: int
    bbox: Tuple[float, float, float, float]
    source: str
    header: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)   # 表头之后的数据行（已渲染）
    markdown_text: str = ""                                # GNN 表在页文本里的原样片段
    merged_into: Optional["PdfTable"] = None               # 跨页续表的归属（被并入前一张）


def _prepare(rows: Sequence[Sequence[Any]]
             ) -> Optional[Tuple[List[str], List[List[str]], int, int, bool]]:
    """清洗 + 表头判定 → (表头, 数据行, 表宽, 表头行下标, 是否识别成功)；不合格返回 None"""
    rendered = [[render_cell(value) for value in row] for row in rows]
    rendered = [row for row in rendered if any(row)]
    if not rendered:
        return None
    if sum(1 for row in rendered for cell in row if cell) < MIN_TABLE_CELLS:
        return None
    width = max(len(row) for row in rendered)
    rendered = [fit_row(row, width) for row in rendered]
    index, ok = detect_header(rendered)
    header = rendered[index]
    data = [row for row in rendered[index + 1:]
            if sum(1 for cell in row if cell) >= MIN_ROW_FILLED]
    if not data:
        return None
    return header, data, width, index, ok


def _sheet(header: List[str], data: List[List[str]], width: int, header_index: int,
           ok: bool, title: str) -> SheetTable:
    return SheetTable(
        title=title,
        columns=column_names(header, width, not ok),
        column_types=[infer_column_type([row[i] for row in data]) for i in range(width)],
        row_count=len(data),
        header_row=header_index + 1,
        header_failed=not ok,
        samples=[list(row) for row in data[:PREVIEW_ROWS]],
    )


def rows_to_sheet_table(rows: Sequence[Sequence[Any]], title: str) -> Optional[SheetTable]:
    """表格行 → 表档案；规模/结构不合格时返回 None"""
    prepared = _prepare(rows)
    if prepared is None:
        return None
    header, data, width, index, ok = prepared
    return _sheet(header, data, width, index, ok, title)


def build_table(rows: Sequence[Sequence[Any]], title: str, page_start: int,
           bbox: Tuple[float, float, float, float], source: str,
           markdown_text: str = "") -> Optional[PdfTable]:
    prepared = _prepare(rows)
    if prepared is None:
        return None
    header, data, width, index, ok = prepared
    return PdfTable(
        sheet=_sheet(header, data, width, index, ok, title),
        page_start=page_start,
        page_end=page_start,
        bbox=bbox,
        source=source,
        header=header,
        rows=data,
        markdown_text=markdown_text,
    )


def tables_from_layout_page(page_layout: Any, page_number: int) -> List[PdfTable]:
    """layout(GNN) 页框 → PdfTable；markdown_text 保留渲染时的原样片段用于精确替换"""
    tables: List[PdfTable] = []
    for box in page_layout.boxes:
        if box.boxclass != "table":
            continue
        detail = getattr(box, "table", None) or {}
        rows = detail.get("extract")
        if not rows:
            continue
        markdown_text = detail.get("markdown") or ""
        if page_layout.full_ocred:
            markdown_text = markdown_text.replace("`", "")
        bbox = detail.get("bbox") or [box.x0, box.y0, box.x1, box.y1]
        table = build_table(rows, f"第{page_number}页 表{len(tables) + 1}", page_number,
                       tuple(bbox), SOURCE_GNN, markdown_text)
        if table is not None:
            tables.append(table)
    return tables


def tables_from_find_tables(page: Any, page_number: int) -> List[PdfTable]:
    """PyMuPDF 原生表格检测（线条/文本）—— 仅作 GNN 漏识别时的兜底"""
    tables: List[PdfTable] = []
    finder = page.find_tables(strategy="lines")
    for tab in finder.tables:
        rows = tab.extract()
        bbox = tuple(tab.bbox)
        table = build_table(rows, f"第{page_number}页 表{len(tables) + 1}", page_number,
                       bbox, SOURCE_LINES)
        if table is not None:
            tables.append(table)
    return tables


def _refresh_sheet(table: PdfTable) -> None:
    """合并数据行后重算表档案的规模、列类型与样本"""
    width = len(table.sheet.columns)
    table.sheet.row_count = len(table.rows)
    table.sheet.column_types = [
        infer_column_type([row[i] for row in table.rows]) for i in range(width)
    ]
    table.sheet.samples = [list(row) for row in table.rows[:PREVIEW_ROWS]]


def merge_continuations(
    tables: List[PdfTable],
) -> Tuple[List[PdfTable], List[Dict[str, Any]]]:
    """跨页续表合并（保守策略）

    三条件同时满足才并：上一表在相邻页、本表顶距页顶 < 40pt、归一列名逐列全等。
    列名对不齐就独立成表并留痕，不猜——宁可把两个半表交给 LLM 自己判断。
    """
    ordered = sorted(tables, key=lambda item: (item.page_start, item.bbox[1]))
    merged: List[PdfTable] = []
    candidates: List[Dict[str, Any]] = []
    for table in ordered:
        previous = merged[-1] if merged else None
        if (previous is not None
                and table.page_start == previous.page_end + 1
                and table.bbox[1] < CONTINUATION_TOP_PT):
            if table.sheet.columns == previous.sheet.columns:
                rows = table.rows
                if rows and rows[0] == table.header:
                    rows = rows[1:]
                previous.rows.extend(rows)
                previous.page_end = table.page_end
                _refresh_sheet(previous)
                table.merged_into = previous
                continue
            candidates.append({
                "prev_pages": [previous.page_start, previous.page_end],
                "next_page": table.page_start,
                "prev_columns": list(previous.sheet.columns),
                "next_columns": list(table.sheet.columns),
            })
        merged.append(table)
    return merged, candidates


def replace_tables(page_text: str, tables: Sequence[PdfTable]) -> Tuple[str, int, int]:
    """把页内表格替换成表档案文本 → (新文本, 替换数, 未命中数)

    GNN 表按原 Markdown 片段精确替换；找不到就保留原文（不半替换）。
    lines 兜底表没有对应 Markdown 块，追加到页尾，页号已在标题里。
    """
    text = page_text
    replaced = 0
    missed = 0
    appended: List[str] = []
    for table in tables:
        if table.merged_into is not None:
            # 已并入上一张表：本页只负责把重复的半表 Markdown 去掉
            if table.markdown_text and table.markdown_text in text:
                text = text.replace(table.markdown_text, "", 1)
            replaced += 1
            continue
        profile = render_profile(table.sheet)
        if table.source == SOURCE_GNN and table.markdown_text:
            if table.markdown_text in text:
                text = text.replace(table.markdown_text, profile, 1)
                replaced += 1
                continue
            missed += 1
            logger.warning(
                "[pdf_tables] 表格 Markdown 片段未命中，保留原文: %s（第 %d 页）",
                table.sheet.title, table.page_start,
            )
            continue
        appended.append(profile)
        replaced += 1
    if appended:
        text = text.rstrip() + "\n\n" + "\n\n".join(appended) + "\n"
    return text, replaced, missed
