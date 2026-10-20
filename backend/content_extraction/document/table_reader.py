"""表格读取器 —— ② 的表档案与 ④ 的行数据共用同一份结构解析

口径只有一份：表头判定、列名占位、行长对齐、单元格归一全部来自 `table_model`。
④ 若自己开 openpyxl，表头判定会与 ③ 看到的列错位，所以行数据也必须从这里取。

xlsx 用 openpyxl 流式读（read_only + data_only），公式单元格数与合并区域从
zip 内的 worksheet XML 直接统计，避免为了这两项把整表再遍历一遍。
"""
import csv
import io
import os
import re
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple
from xml.etree import ElementTree

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from system.logger import logger

from .models import ExtractedDocument, KIND_TABLE, Section
from .table_model import (
    DOC_TEXT_CAP,
    HEADER_SCAN_ROWS,
    MAX_ROWS_READ,
    MAX_SHEETS,
    PREVIEW_ROWS,
    SheetTable,
    blank_row,
    column_names,
    detect_header,
    fit_row,
    fit_width,
    infer_column_type,
    render_cell,
    render_profile,
)

CSV_SHEET_TITLE = "Sheet1"
XLSX_EXTENSIONS = (".xlsx", ".xlsm")
ENCODINGS = ("utf-8-sig", "gbk", "big5")
DELIMITERS = ",;\t|"
# 只为样本区这几行保留公式位置，其余行只统计数量
FORMULA_MARK_ROWS = HEADER_SCAN_ROWS + PREVIEW_ROWS + 5

SKIP_EMPTY = "empty"
SKIP_SINGLE_COLUMN = "single_column"
SKIP_SHEET_LIMIT = "sheet_limit"
SKIP_TEXT_LIMIT = "text_limit"

_NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_FORMULA_CELL = re.compile(rb'<c r="([A-Z]+)(\d+)"[^>]*><f[ />]')
_MERGE_CELL = re.compile(rb'<mergeCell ')


@dataclass
class SheetStats:
    """从 xlsx 包体里直接读出的少量结构信息（不需要遍历单元格）"""
    hidden: bool = False
    merged_regions: int = 0
    formula_cells: int = 0
    formula_rows: Dict[int, Set[int]] = field(default_factory=dict)


@dataclass
class _Structure:
    title: str
    columns: List[str]
    width: int
    header_row: int                      # 1-based 文件行号
    header_failed: bool
    rows: Iterator[Tuple[int, List[Any]]]


def _column_index(letters: bytes) -> int:
    """Excel 列字母 → 0-based 下标（A→0，AA→26）"""
    index = 0
    for char in letters:
        index = index * 26 + (char - 64)
    return index - 1


def _sheet_paths(path: str) -> Dict[str, Tuple[str, bool]]:
    """工作表名 → (包内 xml 路径, 是否隐藏)，顺序与 workbook.xml 一致"""
    with zipfile.ZipFile(path) as archive:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {node.get("Id"): node.get("Target") for node in rels.iter(f"{_NS_PKG}Relationship")}
    found: Dict[str, Tuple[str, bool]] = {}
    for sheet in workbook.iter(f"{_NS_MAIN}sheet"):
        target = targets.get(sheet.get(f"{_NS_REL}id"))
        if not target:
            continue
        normalized = target.lstrip("/")
        if not normalized.startswith("xl/"):
            normalized = f"xl/{normalized}"
        found[sheet.get("name")] = (normalized, sheet.get("state") in ("hidden", "veryHidden"))
    return found


def _xlsx_stats(path: str) -> Dict[str, SheetStats]:
    """公式单元格数、合并区域数、隐藏标记：按工作表名归集"""
    try:
        mapping = _sheet_paths(path)
    except (KeyError, zipfile.BadZipFile, OSError) as e:
        logger.warning(f"[table_reader] 无法读取 xlsx 包体结构统计: {e}")
        return {}
    stats: Dict[str, SheetStats] = {}
    with zipfile.ZipFile(path) as archive:
        for title, (target, hidden) in mapping.items():
            item = SheetStats(hidden=hidden)
            try:
                data = archive.read(target)
            except KeyError:
                data = b""
            for letters, number in _FORMULA_CELL.findall(data):
                item.formula_cells += 1
                row = int(number)
                if row <= FORMULA_MARK_ROWS:
                    item.formula_rows.setdefault(row, set()).add(_column_index(letters))
            item.merged_regions = len(_MERGE_CELL.findall(data))
            stats[title] = item
    return stats


def _fail(path: str, reason: str) -> ValueError:
    return ValueError(f"表格文件无法读取（{os.path.basename(path)}）: {reason}")


def _is_xlsx(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in XLSX_EXTENSIONS


def _open_xlsx(path: str):
    try:
        return load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile) as e:
        raise _fail(path, f"文件已损坏或不是有效的 xlsx：{e}")
    except OSError as e:
        raise _fail(path, str(e))


def _raw_rows(ws) -> Iterator[Tuple[int, List[Any]]]:
    for number, row in enumerate(ws.iter_rows(values_only=True), start=1):
        yield number, list(row)


def _drain_structure(raw: Iterator[Tuple[int, List[Any]]], title: str) -> Optional[_Structure]:
    """读前几行定表头，返回结构 + 表头之后的数据行迭代器（整行空白不计入）"""
    scan: List[Tuple[int, List[Any]]] = []
    for number, row in raw:
        if blank_row(row):
            continue
        scan.append((number, row))
        if len(scan) >= HEADER_SCAN_ROWS:
            break
    if not scan:
        return None
    index, ok = detect_header([row for _, row in scan])
    header_number, header = scan[index]
    width = fit_width(header)
    columns = column_names(header, width, not ok)

    def remaining() -> Iterator[Tuple[int, List[Any]]]:
        yield from scan[index + 1:]
        for number, row in raw:
            if blank_row(row):
                continue
            yield number, row

    return _Structure(title=title, columns=columns, width=width,
                      header_row=header_number, header_failed=not ok, rows=remaining())


def _render_row(values: Sequence[Any], width: int,
                formula_cols: Optional[Set[int]] = None) -> List[str]:
    cells = fit_row(values, width)
    return [render_cell(value, is_formula=bool(formula_cols and index in formula_cols))
            for index, value in enumerate(cells)]


def build_table(structure: _Structure, stats: Optional[SheetStats] = None) -> SheetTable:
    """遍历数据行：统计行数、归一列类型、取前 PREVIEW_ROWS 行样本（全量行不进表档案）"""
    stats = stats or SheetStats()
    kind_samples: List[List[Any]] = [[] for _ in structure.columns]
    samples: List[List[str]] = []
    row_count = 0
    ragged_rows = 0
    truncated = False
    for number, values in structure.rows:
        if row_count >= MAX_ROWS_READ:
            truncated = True
            break
        if len(values) != structure.width:
            ragged_rows += 1
        aligned = fit_row(values, structure.width)
        for index, value in enumerate(aligned):
            kind_samples[index].append(value)
        if len(samples) < PREVIEW_ROWS:
            samples.append(_render_row(values, structure.width, stats.formula_rows.get(number)))
        row_count += 1

    return SheetTable(
        title=structure.title,
        columns=structure.columns,
        column_types=[infer_column_type(values) for values in kind_samples],
        row_count=row_count,
        header_row=structure.header_row,
        header_failed=structure.header_failed,
        merged_regions=stats.merged_regions,
        formula_cells=stats.formula_cells,
        ragged_rows=ragged_rows,
        hidden=stats.hidden,
        rows_truncated=truncated,
        samples=samples,
    )


def _classify(structure: Optional[_Structure]) -> Optional[str]:
    if structure is None:
        return SKIP_EMPTY
    if len(structure.columns) <= 1:
        return SKIP_SINGLE_COLUMN
    return None


def _xlsx_tables(path: str) -> Tuple[List[SheetTable], List[Dict[str, str]]]:
    workbook = _open_xlsx(path)
    tables: List[SheetTable] = []
    skipped: List[Dict[str, str]] = []
    try:
        stats_map = _xlsx_stats(path)
        sheets = list(workbook.worksheets)
        for index, ws in enumerate(sheets):
            title = (ws.title or "").strip() or f"Sheet{index + 1}"
            if index >= MAX_SHEETS:
                skipped.append({"name": title, "reason": SKIP_SHEET_LIMIT})
                continue
            structure = _drain_structure(_raw_rows(ws), title)
            reason = _classify(structure)
            if reason:
                skipped.append({"name": title, "reason": reason})
                continue
            tables.append(build_table(structure, stats_map.get(title)))
        if len(sheets) > MAX_SHEETS:
            logger.warning(f"[table_reader] 工作表共 {len(sheets)} 个，"
                           f"只处理前 {MAX_SHEETS} 个: {path}")
    finally:
        workbook.close()
    return tables, skipped


def _decode_csv(path: str) -> str:
    """按 utf-8-sig → gbk → big5 试解码，全部失败才带替换符兜底

    Windows 导出的中文 CSV 大量是 GBK 无 BOM，这是首要失败源。
    """
    with open(path, "rb") as handle:
        blob = handle.read()
    for encoding in ENCODINGS:
        try:
            text = blob.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\ufffd" not in text:
            return text
    logger.warning(f"[table_reader] CSV 编码均未能干净解码，按 utf-8 替换读取: {path}")
    return blob.decode("utf-8", errors="replace")


def _sniff_delimiter(text: str) -> str:
    sample = text[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=DELIMITERS).delimiter
    except csv.Error:
        return ","


def _csv_rows(path: str) -> Iterator[Tuple[int, List[Any]]]:
    text = _decode_csv(path)
    # tsv 不猜：扩展名已经说明分隔符，Sniffer 在只有一列的样本上会猜错
    delimiter = "\t" if path.lower().endswith(".tsv") else _sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    for number, row in enumerate(reader, start=1):
        yield number, row


def _csv_tables(path: str) -> Tuple[List[SheetTable], List[Dict[str, str]]]:
    structure = _drain_structure(_csv_rows(path), CSV_SHEET_TITLE)
    reason = _classify(structure)
    if reason:
        return [], [{"name": os.path.basename(path), "reason": reason}]
    return [build_table(structure)], []


def read_tables(path: str) -> Tuple[List[SheetTable], List[Dict[str, str]]]:
    """一个表格文件 → (可产章节的表, 被跳过的表及原因)"""
    if _is_xlsx(path):
        return _xlsx_tables(path)
    return _csv_tables(path)


def _xlsx_rows(path: str, sheet_title: str) -> Iterator[Tuple[int, List[Any]]]:
    workbook = _open_xlsx(path)
    try:
        for ws in workbook.worksheets:
            if (ws.title or "").strip() == sheet_title:
                yield from _raw_rows(ws)
                return
    finally:
        workbook.close()


def iter_table_rows(path: str, sheet_title: str) -> Iterator[Dict[str, str]]:
    """④ 的行数据出口：列名 → 渲染后的单元格文本

    表头判定与 ② 完全同一份代码，保证 ③ 标注的列名在这条路径上逐名可用。
    这里不传公式位置 —— `#FORMULA` 只是给 LLM 看的说明，不是取值，
    无缓存值的公式单元格在这里就是空串。
    """
    raw = _xlsx_rows(path, sheet_title) if _is_xlsx(path) else _csv_rows(path)
    structure = _drain_structure(raw, sheet_title or CSV_SHEET_TITLE)
    if _classify(structure):
        return
    for _, values in structure.rows:
        yield dict(zip(structure.columns, _render_row(values, structure.width)))


def build_document(path: str) -> ExtractedDocument:
    """表格文件 → 统一提取结果：一个工作表一个 level-1 叶子，正文为该表的表档案

    渲染总文本超过 DOC_TEXT_CAP 时停止展开后续工作表（防 ③ 的调用次数失控）。
    meta["sheets"] 存各表的结构（列名/类型/行数/样本），③ 压预算时要按它重渲染，
    只看文本无法知道「砍到第几列」；这些结构不进落盘契约，只在进程内用。
    """
    tables, skipped = read_tables(path)
    if not tables:
        raise ValueError(f"表格无可提取内容（{os.path.basename(path)}）: "
                         f"{'、'.join(item['reason'] for item in skipped) or '空文件'}")

    sections: List[Section] = []
    shapes: List[Dict[str, Any]] = []
    used = 0
    for table in tables:
        text = render_profile(table)
        if sections and used + len(text) > DOC_TEXT_CAP:
            skipped.append({"name": table.title, "reason": SKIP_TEXT_LIMIT})
            logger.warning(f"[table_reader] 渲染文本超 {DOC_TEXT_CAP} 字符，"
                           f"后续工作表未展开: {path}")
            continue
        used += len(text)
        sections.append(Section(title=table.title, level=1, text=text,
                                kind=KIND_TABLE))
        shapes.append(asdict(table))

    doc_name, ext = os.path.splitext(os.path.basename(path))
    return ExtractedDocument(doc_name=doc_name, format=ext.lower().lstrip("."),
                             page_count=None, sections=sections,
                             meta={"skipped_sheets": skipped, "sheets": shapes})
