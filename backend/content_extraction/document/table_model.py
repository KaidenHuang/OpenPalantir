"""表格文件的共享层 —— 列类型归一、表头判定、表档案确定性渲染

② 的两个转换器与 ④ 的行读取必须共用这里的口径：同一个文件两次解析
渲染出的文本要逐字节相同（指纹稳定性），且「摘要里看到的列」与「入库用的列」
不能错位。

渲染口径全部写死在这里，改动即改变已有文档的表档案，等价于改指纹算法。
"""
import datetime
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

PREVIEW_ROWS = 2          # 表档案里的样例行数（超预算时 2→1→0）
MAX_CELL_CHARS = 200      # 单个单元格渲染长度
MAX_PROFILE_COLUMNS = 30  # 渲染/入库的列数上限
MAX_SHEETS = 30           # 单文件处理的工作表数
MAX_ROWS_READ = 50000     # 流式读取的行数上限
DOC_TEXT_CAP = 400000     # 单文件渲染总文本上限
HEADER_SCAN_ROWS = 5      # 表头识别最多向下扫几行

# 归一列类型（进表档案列清单的就是这五个）
TYPE_TEXT = "TEXT"
TYPE_NUM = "NUM"
TYPE_DATE = "DATE"
TYPE_BOOL = "BOOL"
TYPE_EMPTY = "EMPTY"

FORMULA_MARK = "#FORMULA"

_NUMBER_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_DATE_RE = re.compile(
    r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"([ T]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?)?$"
)

_SKIP = object()


def kind_of_value(value: Any) -> Optional[str]:
    """Python 单元格值 → 归一类型；空值返回 None

    bool 必须先于 int 判断（bool 是 int 的子类），datetime 先于 date 同理。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return TYPE_BOOL
    if isinstance(value, (datetime.datetime, datetime.date)):
        return TYPE_DATE
    if isinstance(value, (int, float)):
        return TYPE_NUM
    if isinstance(value, str):
        return kind_of_text(value)
    return TYPE_TEXT


def kind_of_text(text: str) -> Optional[str]:
    """文本值 → 归一类型（CSV 全是字符串，不解析的话每列都会是 TEXT）"""
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.lower() in ("true", "false"):
        return TYPE_BOOL
    if _NUMBER_RE.match(stripped.replace(" ", "")):
        return TYPE_NUM
    if _DATE_RE.match(stripped):
        return TYPE_DATE
    return TYPE_TEXT


def infer_column_type(values: Sequence[Any]) -> str:
    """一列的取值 → 归一类型；出现 ≥2 种非空类型时落 TEXT（最保守的一般类）"""
    kinds = set()
    for value in values:
        kind = kind_of_value(value)
        if kind:
            kinds.add(kind)
    if not kinds:
        return TYPE_EMPTY
    if len(kinds) == 1:
        return kinds.pop()
    return TYPE_TEXT


def render_cell(value: Any, is_formula: bool = False) -> str:
    """单元格 → 渲染文本（决定表档案的字节稳定性）

    空值但已知是公式（文件从未被 Excel 重算过，拿不到缓存值）渲染成 #FORMULA，
    与真正的空单元格区分开。
    """
    if value is None:
        return FORMULA_MARK if is_formula else ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    text = str(value).replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    text = text.replace("|", "／").strip()          # 保护 Markdown 行结构
    if len(text) > MAX_CELL_CHARS:
        text = text[:MAX_CELL_CHARS] + "…"
    return text


def normalize_name(value: Any) -> str:
    """列名渲染：与单元格同一套清洗，但不做长度截断（列名是知识主体）"""
    text = render_cell(value)
    return re.sub(r"\s+", " ", text).strip()


def blank_row(row: Sequence[Any]) -> bool:
    return all(render_cell(value) == "" for value in row)


def detect_header(rows: List[List[Any]]) -> Tuple[int, bool]:
    """选出表头行，返回 (行下标, 是否识别成功)

    默认首行；首行不合格（≥50% 空单元格，或多列却全为同一值）时向下扫前
    HEADER_SCAN_ROWS 行，取「非空率高且去重率高」的一行；都找不到就留在首行、
    列名占位成 列1..列M，规模行标识别失败。
    """
    if not rows:
        return 0, False
    if _header_ok(rows[0]):
        return 0, True
    best_index, best_score = -1, -1.0
    for index, row in enumerate(rows[1:HEADER_SCAN_ROWS], start=1):
        if not _header_ok(row):
            continue
        cells = [render_cell(value) for value in row]
        filled = [cell for cell in cells if cell]
        score = len(set(filled)) / len(cells) + len(filled) / len(cells)
        if score > best_score:
            best_index, best_score = index, score
    if best_index < 0:
        return 0, False
    return best_index, True


def _header_ok(row: Sequence[Any]) -> bool:
    cells = [render_cell(value) for value in row]
    filled = [cell for cell in cells if cell]
    if not filled or len(filled) < len(cells) * 0.5:
        return False
    return len(cells) <= 1 or len(set(filled)) > 1


def column_names(header_row: Sequence[Any], width: int, failed: bool) -> List[str]:
    """表头行 → 列名清单；识别失败或列名为空时用占位列名（同名列自动加序号，保证逐名对齐）"""
    names: List[str] = []
    used: Dict[str, int] = {}
    for position in range(width):
        raw = header_row[position] if position < len(header_row) else None
        name = "" if failed else normalize_name(raw)
        if not name:
            name = f"列{position + 1}"
        seen = used.get(name, 0)
        used[name] = seen + 1
        names.append(name if seen == 0 else f"{name}_{seen + 1}")
    return names


def fit_width(header_row: Sequence[Any]) -> int:
    """表宽 = 表头列数

    不按「最宽的一行」定宽：那样一来 ragged 文件会凭空多出几列无名列，
    列名对不上 ③ 的标注。行比表头短的补空、长的并进末列，并记非法列数行。
    """
    return max(len(header_row), 1)


@dataclass
class SheetTable:
    """一个工作表的确定形态描述：② 渲染它，④ 只需要列名与行数据"""
    title: str
    columns: List[str]
    column_types: List[str]
    row_count: int = 0
    header_row: int = 1              # 1-based，表档案里给 LLM 看
    header_failed: bool = False
    merged_regions: int = 0
    formula_cells: int = 0
    ragged_rows: int = 0
    hidden: bool = False
    rows_truncated: bool = False
    samples: List[List[str]] = field(default_factory=list)


def _scale_line(table: SheetTable) -> str:
    parts = [f"共 {table.row_count} 行 × {len(table.columns)} 列",
             f"表头取自第 {table.header_row} 行",
             f"合并单元格 {table.merged_regions} 处",
             f"公式单元格 {table.formula_cells} 处"]
    if table.header_failed:
        parts.append("表头识别失败（用占位列名）")
    if table.ragged_rows:
        parts.append(f"非法列数行 {table.ragged_rows} 条")
    if table.rows_truncated:
        parts.append(f"已按前 {MAX_ROWS_READ} 行统计")
    return " | ".join(parts)


def render_profile(table: SheetTable, preview_rows: int = PREVIEW_ROWS,
                   max_columns: int = MAX_PROFILE_COLUMNS) -> str:
    """表档案四段式：工作表 / 规模 / 列 / 样本

    列清单默认不砍（列名是知识主体），超过 max_columns 只渲染前若干列；
    样本行与列数由调用方（③ 装批压预算）递减，砍到哪一列以返回文本为准。
    """
    title = table.title + (" (隐藏工作表)" if table.hidden else "")
    lines = [f"【工作表】{title}", f"【规模】{_scale_line(table)}"]

    shown = list(zip(table.columns[:max_columns], table.column_types[:max_columns]))
    rendered = [f"{name}({type_})" for name, type_ in shown]
    extra = len(table.columns) - len(shown)
    if extra > 0:
        rendered.append(f"另有 {extra} 列")
    lines.append("【列】" + " | ".join(rendered))

    rows = table.samples[:preview_rows] if table.row_count else []
    if rows:
        header = table.columns[:max_columns]
        lines.append("【样本】")
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "---|" * len(header))
        for row in rows:
            lines.append("| " + " | ".join(row[:max_columns]) + " |")
        if table.row_count > len(rows):
            lines.append(f"（仅展示前 {len(rows)} 行，共 {table.row_count} 行）")
    return "\n".join(lines)


def fit_row(row: Sequence[Any], width: int) -> List[Any]:
    """把一行对齐到表宽：短的补空，多出的列并进末列（保持列名与值的对应不串位）"""
    cells = list(row[:width])
    if len(row) > width and cells:
        extra = [text for text in (render_cell(value) for value in row[width:]) if text]
        if extra:
            tail = render_cell(cells[-1])
            cells[-1] = f"{tail} {' '.join(extra)}".strip()
    while len(cells) < width:
        cells.append(None)
    return cells
