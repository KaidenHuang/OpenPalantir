"""表格文件的 ③ 装批 —— 输入与输出两侧预算同时约束，绝不把单个 sheet 拆到两批

不复用 `text_budget.split_to_budget`：它按句子/换行切，表格切到第二块起没有表头，
列标注会张冠李戴。这里的原子单位是 sheet，装不下就压这个 sheet 自己的档案。

`budget_in` 的减数是 `TABLE_OUTPUT_TOKENS`，不是节点摘要的 2048：
窗口 32768 下若输入按 30520 装箱而实际要留 8192 输出，真实可用只有 24376，
超出的部分会被模型从输入尾部裁掉——被裁掉的正是排在后面的 sheet，
现象是那些 sheet「名字对不上 / 无标注」，日志不会说是窗口挤的。
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from content_extraction.document.table_model import (
    MAX_PROFILE_COLUMNS,
    PREVIEW_ROWS,
    SheetTable,
    render_profile,
)
from system.logger import logger

from .llm import count_tokens
from .text_budget import (
    MIN_BUDGET_TOKENS,
    PROMPT_OVERHEAD_TOKENS,
    char_step,
    input_budget,
)

# 列标注的输出比节点摘要大得多：一列一句中文业务解释，30 列就上千 token。
# 这个额度同时是 input_budget 的减数和发给模型的 max_tokens，两处必须同一个值。
TABLE_OUTPUT_TOKENS = 8192
# 表档案是数字与 `|` 密集的文本，count_tokens 按 4 字符/token 估算会低估，
# 所以输入侧再压一层；标注输出以中文为主，1.5 字/token 属高估，偏保守不再乘系数。
INPUT_SAFETY = 0.6
# 输出估算：每列的标注对象 + 每个 sheet 的摘要与外壳
OUTPUT_PER_COLUMN = 40
OUTPUT_PER_SHEET = 60

# 单 sheet 压不进 budget_in 时的递减档位：先砍样本，再砍列清单
_SHRINK_LADDER = (
    (PREVIEW_ROWS, MAX_PROFILE_COLUMNS),
    (1, MAX_PROFILE_COLUMNS),
    (0, MAX_PROFILE_COLUMNS),
    (0, 20),
    (0, 10),
    (0, 5),
    (0, 1),
)


def table_budget(model_config: Dict[str, Any]) -> Tuple[int, int]:
    """(输入预算, 输出预算) token —— 两侧同时受模型窗口约束

    输入侧复用 text_budget.input_budget，只把减数换成表格的输出额度：窗口公式抄一份
    出来，那边改了这边不会跟着改，而错的又是「看不出来的那侧」。
    """
    available = input_budget(model_config, output_reserve=TABLE_OUTPUT_TOKENS)
    budget_in = max(MIN_BUDGET_TOKENS, int(available * INPUT_SAFETY))
    budget_out = max(MIN_BUDGET_TOKENS, TABLE_OUTPUT_TOKENS - PROMPT_OVERHEAD_TOKENS)
    return budget_in, budget_out


def estimate_output_tokens(sheets: List["TableUnit"]) -> int:
    """一批 sheet 的输出估算：列数 × 每列额度 + sheet 数 × 外壳额度"""
    columns = sum(len(unit.columns) for unit in sheets)
    return columns * OUTPUT_PER_COLUMN + len(sheets) * OUTPUT_PER_SHEET


@dataclass
class TableUnit:
    """一个 sheet 送给 LLM 的形态：渲染后的表档案 + ③ 校验与落盘要用的结构

    `columns` 是**实际渲染进档案**的那几列（宽表砍过列清单时少于总列数），
    列闭合校验与 ④ 的标注都以它为准；`col_count` 记真实列数，供界面显示。
    """
    title: str
    text: str
    columns: List[str]
    row_count: int
    col_count: int
    shrink: Optional[str] = None


def _shrink_note(preview_rows: int, max_columns: int) -> Optional[str]:
    """相对 ② 默认渲染（2 行样本 + 前 30 列），③ 这一档砍了什么"""
    parts = []
    if preview_rows < PREVIEW_ROWS:
        parts.append(f"样本行减至 {preview_rows} 行" if preview_rows else "样本行已去")
    if max_columns < MAX_PROFILE_COLUMNS:
        parts.append(f"列清单截断至 {max_columns} 列")
    return "、".join(parts) or None


def build_unit(shape: Dict[str, Any], budget_in: int) -> TableUnit:
    """sheet 结构 → 装得进预算的表档案（超预算按递减档位压，绝不拆成两批）"""
    table = SheetTable(**shape)
    full_columns = len(table.columns)
    for preview_rows, max_columns in _SHRINK_LADDER:
        text = render_profile(table, preview_rows=preview_rows, max_columns=max_columns)
        if count_tokens(text) <= budget_in:
            note = _shrink_note(preview_rows, max_columns)
            if note:
                logger.info(f"[table_batcher] 表档案压预算: {table.title} "
                            f"{count_tokens(text)}/{budget_in} token，{note}")
            return TableUnit(
                title=table.title, text=text,
                columns=list(table.columns[:max_columns]),
                row_count=table.row_count, col_count=full_columns, shrink=note,
            )
    # 最后一档（1 列 + 无样本）仍超预算：只剩超长列名，硬截并留痕
    text = render_profile(table, preview_rows=0, max_columns=1)
    logger.warning(f"[table_batcher] {table.title} 压到 1 列仍超预算"
                   f"（{count_tokens(text)}>{budget_in}），硬截保留前部")
    return TableUnit(title=table.title, text=text[:char_step(text, budget_in)],
                     columns=list(table.columns[:1]),
                     row_count=table.row_count, col_count=full_columns,
                     shrink="列清单截断至 1 列（档案超长）")


def pack_batches(shapes: List[Dict[str, Any]],
                 model_config: Dict[str, Any]) -> Tuple[List[List[TableUnit]], Tuple[int, int]]:
    """按 sheet 原顺序装箱，返回 (批次, (输入预算, 输出预算))

    加入一个 sheet 需同时满足输入与输出两条预算，任一不满足即封批；
    单个 sheet 永远完整地待在一批里。
    """
    budget_in, budget_out = table_budget(model_config)
    batches: List[List[TableUnit]] = []
    current: List[TableUnit] = []
    for shape in shapes:
        unit = build_unit(shape, budget_in)
        if current:
            trial = current + [unit]
            fits_in = sum(count_tokens(item.text) for item in trial) <= budget_in
            fits_out = estimate_output_tokens(trial) <= budget_out
            if not (fits_in and fits_out):
                batches.append(current)
                current = [unit]
                continue
        current.append(unit)
    if current:
        batches.append(current)
    logger.info(f"[table_batcher] {len(shapes)} 个工作表装为 {len(batches)} 批"
                f"（budget_in={budget_in}, budget_out={budget_out}）")
    return batches, (budget_in, budget_out)


def batch_text(units: List[TableUnit]) -> str:
    """一批 sheet 合并为 prompt 的输入正文"""
    return "\n\n".join(unit.text for unit in units)
