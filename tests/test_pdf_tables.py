"""PDF 表格（pdf_tables）单元测试 —— 行转表档案、跨页续表合并、页内替换（纯函数）"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(BASE, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from content_extraction.document.pdf_tables import (      # noqa: E402
    build_table,
    merge_continuations,
    replace_tables,
    rows_to_sheet_table,
)

pytestmark = pytest.mark.unit


# ── rows_to_sheet_table ─────────────────────────────────────

def test_header_detected_and_types_inferred():
    sheet = rows_to_sheet_table(
        [["地区", "Q1", "Q2"], ["华北", "120", "135"], ["华东", "90", "95"]],
        "第1页 表1",
    )
    assert sheet.columns == ["地区", "Q1", "Q2"]
    assert sheet.column_types == ["TEXT", "NUM", "NUM"]
    assert sheet.row_count == 2
    assert sheet.header_row == 1
    assert sheet.header_failed is False


def test_header_failure_falls_back_to_placeholder_columns():
    """前 5 行都不像表头（空得多或全同值）→ 用占位列名，行数据照常保留"""
    rows = [["Report", "", "", ""],
            ["a", "a", "", ""],
            ["b", "b", "", ""]]
    sheet = rows_to_sheet_table(rows, "第1页 表1")
    assert sheet.header_failed is True
    assert sheet.columns == ["列1", "列2", "列3", "列4"]
    assert sheet.row_count == 2


def test_field_value_pseudo_table_is_tolerated():
    """「字段：值」型的键值区被 GNN 标成表时照常做表档案，不崩"""
    sheet = rows_to_sheet_table([["姓名", "张三"], ["年龄", "30"], ["城市", "上海"]],
                                "第1页 表1")
    assert len(sheet.columns) == 2
    assert sheet.row_count == 2


def test_too_few_cells_is_rejected():
    assert rows_to_sheet_table([["A", "B"], ["", "1"]], "t") is None


def test_header_only_is_rejected():
    assert rows_to_sheet_table([["A", "B", "C", "D"]], "t") is None


def test_cell_pipe_is_escaped():
    """单元格里的竖线会被替换，否则表档案的样本表格结构被破坏"""
    sheet = rows_to_sheet_table([["列A", "列B"], ["x|y", "1"], ["z", "2"]], "t")
    assert "|" not in "".join("".join(row) for row in sheet.samples)


# ── 跨页续表合并 ────────────────────────────────────────────

HEADER = ["地区", "Q1", "Q2"]


def _table(rows, page, top=100.0, markdown=""):
    return build_table(rows, f"第{page}页 表1", page, (0, top, 300, 500), "gnn", markdown)


def test_continuation_merges_rows_and_extends_page_range():
    first = _table([HEADER, ["华北", "120", "135"]], 1)
    second = _table([HEADER, ["华南", "90", "95"]], 2, top=10.0)
    merged, candidates = merge_continuations([first, second])
    assert len(merged) == 1
    assert candidates == []
    assert merged[0].page_start == 1 and merged[0].page_end == 2
    assert merged[0].sheet.row_count == 2
    assert second.merged_into is first


def test_continuation_drops_repeated_header():
    first = _table([HEADER, ["华北", "120", "135"]], 1)
    second = _table([HEADER, ["华南", "90", "95"]], 2, top=10.0)
    merged, _ = merge_continuations([first, second])
    assert merged[0].rows == [["华北", "120", "135"], ["华南", "90", "95"]]


def test_column_mismatch_is_not_merged_but_recorded():
    first = _table([HEADER, ["华北", "120", "135"]], 1)
    second = _table([["区域", "Q1", "Q2"], ["华南", "90", "95"]], 2, top=10.0)
    merged, candidates = merge_continuations([first, second])
    assert len(merged) == 2
    assert second.merged_into is None
    assert len(candidates) == 1
    assert candidates[0]["next_page"] == 2


def test_table_low_on_next_page_is_not_a_continuation():
    first = _table([HEADER, ["华北", "120", "135"]], 1)
    second = _table([HEADER, ["华南", "90", "95"]], 2, top=200.0)
    merged, _ = merge_continuations([first, second])
    assert len(merged) == 2


# ── 页内替换 ────────────────────────────────────────────────

PIPE_BLOCK = "| 地区 | Q1 | Q2 |\n|---|---|---|\n| 华北 | 120 | 135 |\n| 华东 | 90 | 95 |"


def test_gnn_table_block_is_replaced_by_profile():
    table = _table([HEADER, ["华北", "120", "135"], ["华东", "90", "95"]], 1,
                   markdown=PIPE_BLOCK)
    text, replaced, missed = replace_tables("# 报告\n\n正文\n\n" + PIPE_BLOCK + "\n", [table])
    assert replaced == 1 and missed == 0
    assert "【工作表】第1页 表1" in text
    # 原管道表块被换成表档案（表档案的样本区自带一份同表头，所以只数出现次数）
    assert text.count("| 地区 | Q1 | Q2 |") == 1
    assert "正文" in text


def test_unmatched_markdown_keeps_original_text():
    table = _table([HEADER, ["华北", "120", "135"]], 1, markdown="| 不存在的表 |")
    original = "# 报告\n\n正文里没有这张表\n"
    text, replaced, missed = replace_tables(original, [table])
    assert text == original
    assert replaced == 0 and missed == 1


def test_find_tables_fallback_profile_is_appended():
    table = build_table([HEADER, ["华北", "120", "135"]], "第1页 表1", 1,
                        (0, 100, 300, 500), "lines")
    text, replaced, _ = replace_tables("正文", [table])
    assert replaced == 1
    assert text.startswith("正文")
    assert "【工作表】第1页 表1" in text


def test_merged_continuation_block_is_removed_without_duplicating_profile():
    first = _table([HEADER, ["华北", "120", "135"]], 1, markdown=PIPE_BLOCK)
    second_block = "| 地区 | Q1 | Q2 |\n|---|---|---|\n| 华南 | 90 | 95 |"
    second = _table([HEADER, ["华南", "90", "95"]], 2, top=10.0, markdown=second_block)
    merged, _ = merge_continuations([first, second])

    page1, _, _ = replace_tables("# 报告\n\n" + PIPE_BLOCK + "\n", merged)
    page2, _, _ = replace_tables("# 续表\n\n" + second_block + "\n", [second])

    assert "【工作表】" in page1
    assert "华南" in page1                     # 合并后的行在首页表档案里
    assert "【工作表】" not in page2            # 续页不再重复输出表档案
    assert "华南" not in page2
