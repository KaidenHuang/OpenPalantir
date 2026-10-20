"""
文档摘要生成 —— 唯一的 LLM 环节

吃 content_extraction 的 ExtractedDocument，产出摘要树 dict
（落盘 JSON 的 structure 字段契约）：
  叶子节点: {title, node_id, kind, page_start, page_end, summary, text}
  父节点:   {title, node_id, kind, page_start, page_end, summary, text, nodes}
  表格叶子: 另带 {table_columns, table_meta}（逐列角色 + 行列数 + 列间关系）

kind 来自 ② 的 Section.kind（prose | table），文档级 kind 是同一份声明的聚合：
④ 按它分派，不再用扩展名反推「这个文件是不是表格」。

字段名统一用 summary：下游四处（树导航 / 摘要检索 / Wiki 文档页 / 前端摘要树）
都只读 summary，父节点另起 key 会让它的概览在每一处都显示为空。
叶子还是父节点由结构（有无 nodes）区分，不在字段名里重复表达。

自底向上生成：叶子取自身正文，父节点取「自身正文 + 子节点摘要列表」，
父节点不再重送子树全文（旧做法让全文按树深重复计入输入 token）。
单次输入超过模型窗口预算时，节点内按句子边界切块分别摘要再归并，
绝不把尾部静默丢掉。

表格文件是另一条调度：一个工作表一个叶子，按 sheet 装箱（绝不拆开一个 sheet），
一次调用同时出该批 sheet 的摘要与逐列标注，JSON 契约见 prompts/prompt_table_node.md。

LLM 单节点失败时不打断任务：降级为使用原文作为摘要并记 warning；
表格分支不能照抄这条降级（原文不是标注），失败时 summary 回退表档案、
列标注置空并在结果的 table_report 里留痕。
完全没有可用模型时抛 RuntimeError（由任务层判定为模型未配置）。
"""
import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

from system.logger import logger
from .llm import (
    call_llm_async,
    call_llm_json_async,
    count_tokens,
    get_model_config,
    load_prompt,
)
from .table_batcher import (
    TABLE_OUTPUT_TOKENS,
    TableUnit,
    batch_text,
    pack_batches,
)
from .text_budget import input_budget, split_to_budget, truncate_to_budget
from .tree_utils import (
    convert_sections,
    flatten_by_depth,
    is_table_tree,
    node_content,
    page_span,
)
from content_extraction import ExtractedDocument
from content_extraction.document.models import KIND_PROSE, KIND_TABLE

# 模板只在导入时读一次：缺文件立刻在应用启动时抛错，且省掉每批次一次磁盘读
_NODE_SUMMARY_PROMPT = load_prompt("prompt_summary_node.md")
_DOC_DESCRIPTION_PROMPT = load_prompt("prompt_doc_description.md")
_TABLE_NODE_PROMPT = load_prompt("prompt_table_node.md")

DEFAULT_SUMMARY_TOKEN_THRESHOLD = 200
# 切块归并的轮数上限：每轮要把内容压进预算，压不动就兜底截断，不允许无限递归
MAX_REDUCE_ROUNDS = 4
# 一批 sheet 的标注里缺列比例超过它判本次标注失败（宁可无标注，不要半套标注）
TABLE_MISSING_COLUMN_RATIO = 0.3


async def _summarize_once(text: str, model_config: Dict[str, Any]) -> str:
    """一次 LLM 摘要调用；失败降级为传入的文本"""
    try:
        prompt = _NODE_SUMMARY_PROMPT.replace("{text}", text)
        summary = (await call_llm_async(model_config, prompt)).strip()
        return summary or text
    except Exception as e:
        logger.warning(f"[summary_generation] 节点摘要 LLM 调用失败，降级为原文: {e}")
        return text


async def _reduce_to_budget(text: str, model_config: Dict[str, Any], budget: int) -> str:
    """把内容压进预算：超预算就切块分别摘要，各块摘要拼回来后仍超则再切一轮"""
    content = text
    for _ in range(MAX_REDUCE_ROUNDS):
        parts = split_to_budget(content, budget)
        if len(parts) < 2:
            return content
        logger.info(f"[summary_generation] 输入超预算（{count_tokens(content)}>{budget}），"
                    f"切为 {len(parts)} 块分别摘要")
        summaries = await asyncio.gather(
            *[_summarize_once(part, model_config) for part in parts]
        )
        content = "\n\n".join(s for s in summaries if s)
    logger.warning(f"[summary_generation] 归并 {MAX_REDUCE_ROUNDS} 轮仍超预算，交由兜底截断")
    return content


async def _summarize_text(text: str, model_config: Dict[str, Any], threshold: int,
                          budget: int) -> str:
    """单节点摘要输入 → 摘要；短文本不做 LLM（直接原文，与旧行为一致）；超预算先切块归并"""
    if count_tokens(text) < threshold:
        return text

    content = await _reduce_to_budget(text, model_config, budget)
    if count_tokens(content) > budget:
        content = truncate_to_budget(content, budget)
    return await _summarize_once(content, model_config)


def _description_tree(nodes: List[dict]) -> List[dict]:
    """给文档描述用的骨架树：title + summary + 层级，不带正文"""

    def _walk(list_: List[dict]) -> List[dict]:
        out = []
        for node in list_:
            entry = {
                "title": node["title"],
                "node_id": node["node_id"],
                "summary": node.get("summary") or "",
            }
            children = node.get("children") or []
            if children:
                entry["nodes"] = _walk(children)
            out.append(entry)
        return out

    return _walk(nodes)


async def _generate_doc_description(nodes: List[dict], model_config: Dict[str, Any]) -> str:
    try:
        structure = json.dumps(_description_tree(nodes), ensure_ascii=False, indent=2)
        budget = input_budget(model_config)
        if count_tokens(structure) > budget:
            logger.warning(f"[summary_generation] 文档骨架超出预算（{count_tokens(structure)}>"
                           f"{budget}），仅保留标题层级")
            structure = json.dumps(_title_tree(nodes), ensure_ascii=False)
        prompt = _DOC_DESCRIPTION_PROMPT.replace("{structure}", structure)
        return (await call_llm_async(model_config, prompt)).strip()
    except Exception as e:
        logger.warning(f"[summary_generation] 文档描述生成失败，降级为空描述: {e}")
        return ""


def _title_tree(nodes: List[dict]) -> List[Any]:
    """只含标题的骨架，供骨架超预算时降级使用"""

    def _walk(list_):
        out = []
        for node in list_:
            children = node.get("children") or []
            out.append([node["title"], _walk(children)] if children else node["title"])
        return out

    return _walk(nodes)


def _emit(nodes: List[dict]) -> List[dict]:
    """内部节点 → 落盘结构：叶子与父节点都带 summary + text，父节点另带 nodes

    父节点自身正文一并落盘：摘要树是内容抽取（阶段④）与树导航的唯一正文来源，
    不落盘则该部分正文永远进不了抽取批次。
    表格叶子另带 table_columns / table_meta（④ 的规则装配与界面字段列表读它们）。
    """
    out: List[dict] = []
    for node in nodes:
        page_start, page_end = page_span(node)
        entry = {
            "title": node["title"],
            "node_id": node["node_id"],
            "kind": node["kind"],
            "page_start": page_start,
            "page_end": page_end,
            "summary": node.get("summary", ""),
            "text": node["own_text"],
        }
        for key in ("table_columns", "table_meta"):
            if key in node:
                entry[key] = node[key]
        if node["children"]:
            entry["nodes"] = _emit(node["children"])
        out.append(entry)
    return out


# ── 表格分支：一次调用出「摘要 + 逐列角色标注」 ──────────────────────────

def _build_table_prompt(text: str, domain: str) -> str:
    from ontology.prompt import prompt_sections

    sections = prompt_sections(domain)
    return (_TABLE_NODE_PROMPT
            .replace("{entity_types}", sections["entity_types"])
            .replace("{link_types}", sections["link_types"])
            .replace("{property_types}", sections["property_types"])
            .replace("{text}", text))


def _classify_reply(data: Any, truncated: bool) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(解析结果, 截断标记) → (sheets 对象, 失败原因)

    截断与垃圾输出两条成因分别留痕：前者拆批重发有用，后者只能降级。
    """
    if truncated:
        return None, "table_annotation_truncated"
    if not isinstance(data, dict):
        return None, "table_annotation_invalid"
    return data, None


def _clean_columns(entry: dict, unit: TableUnit) -> Tuple[Optional[List[dict]], Optional[str]]:
    """列闭合校验：只认输入列名，缺列补 r=none，缺失率过高判本次标注失败"""
    raw_columns = [c for c in (entry.get("columns") or []) if isinstance(c, dict)]
    by_name: Dict[str, dict] = {}
    for column in raw_columns:
        name = column.get("n")
        if isinstance(name, str) and name in unit.columns and name not in by_name:
            by_name[name] = column
    missing = [name for name in unit.columns if name not in by_name]
    if unit.columns and len(missing) / len(unit.columns) > TABLE_MISSING_COLUMN_RATIO:
        return None, "table_columns_missing"

    entity_columns = []
    columns = []
    for name in unit.columns:
        source = by_name.get(name)
        role = (source or {}).get("r")
        role = role if role in ("entity", "attribute", "none") else "none"
        item = {"n": name, "r": role, "d": str((source or {}).get("d") or "").strip()}
        if role == "entity":
            item["t"] = str((source or {}).get("t") or "").strip() or "other"
            entity_columns.append(name)
        columns.append(item)

    primary = entry.get("primary")
    if primary not in entity_columns:
        # 模型把主列填成了属性列/不存在的列：只有一个 entity 列时它就是这张表的主语，
        # 多个则不猜（primary 为空 → ④ 的属性列无处可挂，按丢弃计数，比臆造归属诚实）
        primary = entity_columns[0] if len(entity_columns) == 1 else ""
    for item in columns:
        item["primary"] = item["n"] == primary
    return columns, None


def _clean_rels(entry: dict, entity_columns: List[str]) -> List[dict]:
    """关系只保留两个端点都是本表 entity 列的（跨列拼错直接丢，不做模糊匹配）"""
    rels = []
    seen = set()
    for rel in entry.get("rels") or []:
        if not isinstance(rel, dict):
            continue
        subject, obj = rel.get("s"), rel.get("o")
        predicate = str(rel.get("p") or "").strip()
        if subject not in entity_columns or obj not in entity_columns:
            continue
        if subject == obj or not predicate or (subject, predicate, obj) in seen:
            continue
        seen.add((subject, predicate, obj))
        rels.append({"s": subject, "p": predicate, "o": obj})
    return rels


def _clean_sheet(entry: dict, unit: TableUnit) -> Tuple[Optional[dict], Optional[str]]:
    columns, reason = _clean_columns(entry, unit)
    if reason:
        return None, reason
    entity_columns = [item["n"] for item in columns if item["r"] == "entity"]
    summary = str(entry.get("summary") or "").strip() or unit.text
    # 主列只落在 columns 的 primary 标记上（④ 与界面都读它），不再另存 sheet 级字段
    return {"summary": summary, "columns": columns,
            "rels": _clean_rels(entry, entity_columns)}, None


async def _annotate_batch(units: List[TableUnit], model_config: Dict[str, Any],
                          domain: str, report: Dict[str, Any],
                          can_split: bool = True) -> Dict[str, dict]:
    """一批 sheet 的一次调用 → {工作表名: 标注}；失败的工作表不在返回值里（调用方按无标注降级）

    表格分支不复用 _summarize_once 的「失败就用原文」：原文是表档案，
    把它当摘要可以，当标注解析会造出不存在的列。
    """
    prompt = _build_table_prompt(batch_text(units), domain)
    report["calls"] += 1
    try:
        data, truncated = await call_llm_json_async(model_config, prompt, TABLE_OUTPUT_TOKENS)
    except Exception as e:
        logger.warning(f"[table_summary] 标注调用异常，该批 {len(units)} 个表降级为无标注: {e}")
        report["invalid"].extend(unit.title for unit in units)
        return {}

    data, reason = _classify_reply(data, truncated)
    if reason:
        # 截断先半批重试一次（拆批，不降级）：整批重跑还是同样长，多半还是截断
        if truncated and can_split and len(units) > 1:
            mid = len(units) // 2
            logger.warning(f"[table_summary] 输出截断，{len(units)} 个表的批次拆为 "
                           f"{mid}+{len(units) - mid} 重试")
            report["split_retry"].extend(unit.title for unit in units)
            left = await _annotate_batch(units[:mid], model_config, domain, report,
                                         can_split=False)
            left.update(await _annotate_batch(units[mid:], model_config, domain, report,
                                              can_split=False))
            return left
        report["truncated" if truncated else "invalid"].extend(unit.title for unit in units)
        logger.warning(f"[table_summary] {reason}: {[u.title for u in units]}")
        return {}

    by_title: Dict[str, dict] = {}
    annotated_titles = set()
    for entry in data.get("sheets") or []:
        if not isinstance(entry, dict):
            continue
        title = entry.get("title")
        if not isinstance(title, str):
            continue
        annotated_titles.add(title)
        unit = next((item for item in units if item.title == title), None)
        if unit is None or title in by_title:
            continue
        cleaned, sheet_reason = _clean_sheet(entry, unit)
        if sheet_reason:
            report["columns_missing"].append(title)
            logger.warning(f"[table_summary] {sheet_reason}: {title}")
            continue
        by_title[title] = cleaned

    for unit in units:
        if unit.title not in annotated_titles:
            report["unmatched"].append(unit.title)
            logger.warning(f"[table_summary] 标注里没有工作表 {unit.title}（名字对不上，不做模糊匹配）")
    return by_title


async def _build_result(extracted: ExtractedDocument, tree: List[dict],
                        model_config: Dict[str, Any],
                        generate_doc_description: bool) -> Dict[str, Any]:
    """两条调度共用的产出骨架：落盘结构 + 文档描述

    文档级 kind 由同一棵树的节级声明聚合而成，是 ④ 分派的唯一依据。
    """
    doc_description = ""
    if generate_doc_description:
        doc_description = await _generate_doc_description(tree, model_config)
    return {
        "doc_name": extracted.doc_name,
        "format": extracted.format,
        "kind": KIND_TABLE if is_table_tree(tree) else KIND_PROSE,
        "page_count": extracted.page_count,
        "structure": _emit(tree),
        "doc_description": doc_description,
    }


async def _summarize_tables(extracted: ExtractedDocument, tree: List[dict],
                            model_config: Dict[str, Any],
                            domain: str, generate_doc_description: bool) -> Dict[str, Any]:
    """表格文件 → 每个 sheet 一个叶子：summary 是业务摘要，table_columns 是逐列角色"""
    shapes = extracted.meta.get("sheets") or []
    batches, (budget_in, budget_out) = pack_batches(shapes, model_config)
    units = [unit for batch in batches for unit in batch]
    report: Dict[str, Any] = {
        "sheet_count": len(units), "batch_count": len(batches), "calls": 0,
        "budget_in": budget_in, "budget_out": budget_out,
        "truncated": [], "split_retry": [], "invalid": [],
        "columns_missing": [], "unmatched": [],
        "shrunken": {unit.title: unit.shrink for unit in units if unit.shrink},
    }

    annotated: Dict[str, dict] = {}
    for batch in batches:
        annotated.update(await _annotate_batch(batch, model_config, domain, report))

    for node, unit in zip(tree, units):
        entry = annotated.get(unit.title)
        if entry is None:
            node["summary"] = unit.text
            node["table_columns"] = []
            node["table_meta"] = {"row_count": unit.row_count, "col_count": unit.col_count,
                                  "rels": [], "skipped_reason": unit.shrink}
            continue
        node["summary"] = entry["summary"]
        node["table_columns"] = entry["columns"]
        node["table_meta"] = {"row_count": unit.row_count, "col_count": unit.col_count,
                              "rels": entry["rels"], "skipped_reason": unit.shrink}

    result = await _build_result(extracted, tree, model_config, generate_doc_description)
    result["table_report"] = report
    return result


async def _summarize(extracted: ExtractedDocument, tree: List[dict],
                     model_config: Dict[str, Any],
                     threshold: int, generate_doc_description: bool) -> Dict[str, Any]:
    budget = input_budget(model_config)

    # 深层在前：子节点摘要先出，父节点才有的可引用
    for level in flatten_by_depth(tree):
        tasks = [_summarize_text(node_content(node), model_config, threshold, budget)
                 for node in level]
        summaries = await asyncio.gather(*tasks)
        for node, summary in zip(level, summaries):
            node["summary"] = summary

    return await _build_result(extracted, tree, model_config, generate_doc_description)


def summarize_document(extracted: ExtractedDocument,
                       model_config: Optional[Dict[str, Any]] = None,
                       summary_token_threshold: int = DEFAULT_SUMMARY_TOKEN_THRESHOLD,
                       generate_doc_description: bool = True,
                       domain: str = "general") -> dict:
    """ExtractedDocument → 摘要树 dict（落盘前的完整结果 dict）

    ② 声明每个章节都是表格（Section.kind）时走独立调度：一个工作表一次调用出
    「摘要 + 逐列角色标注」，非表格路径（章节树自底向上摘要）不改分派依据以外的逻辑。

    Raises:
        RuntimeError: 模型管理中没有可用模型
    """
    if model_config is None:
        model_config = get_model_config()
    if not model_config:
        raise RuntimeError("没有可用的模型，请先在模型管理中配置并激活模型")

    tree = convert_sections(extracted)
    if is_table_tree(tree):
        return asyncio.run(_summarize_tables(extracted, tree, model_config, domain,
                                             generate_doc_description))
    return asyncio.run(_summarize(extracted, tree, model_config,
                                  summary_token_threshold, generate_doc_description))
