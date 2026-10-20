"""④ 实体抽取（文档侧·表格分支）—— ③ 的列标注 + 源文件真实行值 → 列实体/列间关系

「④ 不重读源文件」在这条分支是显式例外：全表行值是数据不是文章，塞进摘要 JSON 会让
摘要文件变成几十 MB 的数据副本，破坏「摘要树是知识不是数据」的定位。换来的两条硬要求：
1. 取行只走 `table_reader.iter_table_rows`，表头判定与② 同一份代码，否则 ③ 标注的
   列名在这条路径上会错位；
2. 落库前校验源文件 MD5 == 摘要 content_hash，不等直接终止（半新半旧比失败更难查，
   而且不一致时继续写会让下一轮代际回收把新版本产出当旧代误摘）。

零 LLM 调用：列角色、实体类型、列间关系都由 ③ 的标注决定，这里只做装配、上限守卫与
本体校验；`batch_total/batch_failed` 恒为 0，`guard_llm_available` 因此不会误判。
"""
import os
from typing import Any, Dict, Iterator, List, Optional, Tuple

from content_extraction.document.models import KIND_TABLE
from content_extraction.document.table_model import (
    MAX_ROWS_READ,
    TYPE_NUM,
    kind_of_text,
)
from content_extraction.document.table_reader import iter_table_rows
from system.logger import logger

# 单列 distinct 上限：越界的典型是订单号、时间戳、明细行 ID，它们不是业务对象
COLUMN_ENTITY_LIMIT = 5000
# 单 sheet 实体总数上限：超了只保主列，避免一次导入把图谱写爆
SHEET_ENTITY_LIMIT = 20000
MIN_VALUE_LENGTH = 2
# 建值实体时一律跳过的停用值（合计行、占位行不算业务对象）——纯 ④ 的取值口径，
# 与 ② 的表档案渲染无关，改它不动任何文档指纹
STOPWORD_VALUES = frozenset({"合计", "小计", "平均", "总计", "暂无", "N-A", "NA", "N/A", "-"})

SKIPPED_NO_ANNOTATION = "无列标注"
ABORT_FINGERPRINT = "源文件指纹与摘要不一致"
# 词表外类型原值存放的键：它与列名共用 attributes 这一个命名空间
RAW_TYPE_KEY = "raw_type"


class _Sheet:
    """摘要里一个表格叶子的标注 → 装配视图（列角色、主列、列间关系）"""

    def __init__(self, node: Dict[str, Any]):
        self.title: str = str(node.get("title") or "").strip()
        columns = [c for c in node.get("table_columns") or []
                   if isinstance(c, dict) and isinstance(c.get("n"), str) and c["n"]]
        self.entity: List[str] = []
        self.attribute: List[str] = []
        self.types: Dict[str, str] = {}
        for column in columns:
            name = column["n"]
            role = column.get("r")
            if role == "entity":
                self.entity.append(name)
                self.types[name] = str(column.get("t") or "").strip()
            elif role == "attribute":
                self.attribute.append(name)
        # ③ 已经校验过一轮，这里按落盘 JSON 重新校验：手改或旧版摘要不能污染图谱
        raw_rels = (node.get("table_meta") or {}).get("rels") or []
        self.rels: List[Dict[str, str]] = []
        for rel in raw_rels:
            if not isinstance(rel, dict):
                continue
            predicate = str(rel.get("p") or "").strip()
            if not predicate:
                continue
            if rel.get("s") in self.entity and rel.get("o") in self.entity:
                self.rels.append({"s": rel["s"], "p": predicate, "o": rel["o"]})
        primary = next((c["n"] for c in columns if c.get("primary")), "")
        self.primary = primary if primary in self.entity else ""


def import_tables(summary: Dict[str, Any], datasource: str, *, domain: str = "general",
                  evidence_hash: Optional[str] = None) -> Dict[str, Any]:
    """表格摘要 → 列实体与列间关系（纯规则，零 LLM）

    datasource 必须是文档 URI（`DOC://{source_id}/{相对路径}`）：代际回收按它摘除佐证，
    拿 sheet 名当 datasource 会让重跑一篇文档清掉别人的图谱产出。
    """
    leaves = [node for node in _walk_leaves(summary.get("structure") or [])
              if node.get("table_columns")]
    if not leaves:
        logger.info(f"[table_import] {datasource}: 摘要声明是表格，却没有一个带列标注的叶子，跳过导入")
        return _result(0, 0, skipped=SKIPPED_NO_ANNOTATION)

    full_path = resolve_source_file(datasource)
    _verify_fingerprint(full_path, str(summary.get("content_hash") or ""))

    doc_name = str(summary.get("doc_name") or os.path.basename(full_path))
    entities: Dict[str, Dict[str, Any]] = {}
    # 边按三元组收敛：跨 sheet 的同一行内关系重复出现，落库前一份就够
    relationships: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    report: Dict[str, Any] = {
        "sheets": [], "rows_read": 0,
        "column_downgraded_high_cardinality": [],
        "sheet_entity_limit_hit": [],
        "attribute_dropped_no_primary": 0,
        "attribute_key_reserved": [],
        "rel_endpoint_dropped": 0,
        "values_filtered": {"short": 0, "numeric": 0, "stopword": 0},
    }

    for node in leaves:
        sheet = _Sheet(node)
        if not sheet.entity:
            logger.info(f"[table_import] {datasource} / {sheet.title}: 没有实体列，无可建实体")
            continue
        counts, attrs, triples, rows_read = _scan_rows(sheet, full_path, report)
        if not rows_read:
            logger.warning(f"[table_import] {datasource} / {sheet.title}: 源文件里读不到行，"
                           "该 sheet 不导入")
            continue
        report["sheets"].append(sheet.title)
        report["rows_read"] += rows_read
        kept = _kept_columns(sheet, counts, report)
        _collect(sheet, kept, attrs, triples, doc_name, domain, entities,
                 relationships, report)

    entity_list = list(entities.values())
    rel_list = list(relationships.values())
    entity_count, rel_count = 0, 0
    if entity_list:
        from knowledge_graph.entity_data_store import EntityDataStore

        entity_count, rel_count = EntityDataStore.save_all(
            entity_list, rel_list, datasource=datasource,
            evidence_hash=evidence_hash,
        )
    else:
        logger.info(f"[table_import] {datasource}: 按标注与上限守卫装配后无可落库实体")

    logger.info(f"[table_import] {datasource}: 实体 {entity_count}, 关系 {rel_count}, "
                f"sheet {len(report['sheets'])}, 行 {report['rows_read']}, "
                f"高基数降级 {len(report['column_downgraded_high_cardinality'])} 列")
    return _result(entity_count, rel_count, report=report)


def _result(entity_count: int, rel_count: int, skipped: str = "",
            report: Optional[dict] = None) -> Dict[str, Any]:
    """与 LLM 分支同形的结果（守卫与任务层只读这几个字段）

    表格分支的实体可达数万，明细不回传任务结果；图谱就是它的落点，界面走图查询。
    """
    result: Dict[str, Any] = {
        "entity_count": entity_count,
        "relationship_count": rel_count,
        # 表格导入零 LLM 调用：批次计数为 0，守卫判「批次全灭」时不会误报警
        "batch_total": 0,
        "batch_failed": 0,
        "table_import_skipped": skipped,
    }
    if report is not None:
        result["table_report"] = report
    return result


def _walk_leaves(nodes: List[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
    """摘要树里的表格叶子：认 ② 声明的 kind=table，不靠「有没有列标注」反推

    列标注为空（③ 标注失败降级）的叶子照样取出，由调用方按「无列标注」统计；
    用 table_columns 判表格会把这种叶子当成非表格悄悄漏掉。父节点只带 nodes。
    """
    for node in nodes:
        if node.get("kind") == KIND_TABLE:
            yield node
        yield from _walk_leaves(node.get("nodes") or [])


def resolve_source_file(datasource: str) -> str:
    """文档来源 URI → 源文件绝对路径（④ 重读源文件的位置口径）"""
    from config.database import SessionLocal
    from source_registry.document.registry import document_source_registry
    from summary_generation.document import store as summary_generator
    from utils.path_guard import safe_join

    source_id, file_path = summary_generator.parse_datasource(datasource)
    if not source_id or not file_path:
        raise ValueError(f"表格导入需要文档来源 URI（DOC://…）: {datasource}")
    db = SessionLocal()
    try:
        base_path = document_source_registry.root_path(db, source_id, quiet=True)
    finally:
        db.close()
    if not base_path:
        raise FileNotFoundError(f"文档源不存在或已删除: {source_id}")
    return safe_join(base_path, file_path)


def _verify_fingerprint(full_path: str, content_hash: str) -> None:
    """源文件 MD5 与摘要记录的指纹必须一致，否则本轮判失败并终止写库"""
    from summary_generation.document import store as summary_generator

    if not os.path.isfile(full_path):
        raise FileNotFoundError(f"源文件已不存在，无法按摘要导入: {full_path}")
    if not content_hash:
        raise ValueError(f"{ABORT_FINGERPRINT}: 摘要未记录 content_hash")
    actual = summary_generator.file_content_hash(full_path)
    if actual != content_hash:
        logger.error(f"[table_import] {ABORT_FINGERPRINT}: {full_path} "
                     f"MD5={actual} ≠ 摘要 {content_hash}")
        raise ValueError(f"{ABORT_FINGERPRINT}（table_import_aborted）: 源文件已变更，"
                         "请重新生成摘要后再导入")


def _filter_reason(value: str) -> str:
    """不产实体的取值：过短、纯数字、停用词（合计/小计/占位行不是业务对象）"""
    if len(value) < MIN_VALUE_LENGTH:
        return "short"
    if value in STOPWORD_VALUES:
        return "stopword"
    if kind_of_text(value) == TYPE_NUM:
        return "numeric"
    return ""


def _scan_rows(sheet: _Sheet, full_path: str,
               report: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, int]],
                                                Dict[str, Dict[str, str]],
                                                Dict[Tuple[str, str, str], Tuple[str, str]],
                                                int]:
    """一次流式扫描：每列 distinct 值计数 + 主列属性的取值 + 行内三元组

    内存按 distinct 值数计，不按行数计：五万行明细表的不同取值本来就少，
    逐行留副本会把导入本身变成内存瓶颈。
    """
    counts: Dict[str, Dict[str, int]] = {name: {} for name in sheet.entity}
    attrs: Dict[str, Dict[str, str]] = {}
    triples: Dict[Tuple[str, str, str], Tuple[str, str]] = {}
    rows_read = 0

    for row in iter_table_rows(full_path, sheet.title):
        if rows_read >= MAX_ROWS_READ:
            logger.warning(f"[table_import] {sheet.title} 行数超过 {MAX_ROWS_READ}，"
                           "其余行不参与装配")
            break
        rows_read += 1

        valid: Dict[str, str] = {}
        for name, value in _filled(row, sheet.entity).items():
            reason = _filter_reason(value)
            if reason:
                report["values_filtered"][reason] += 1
                continue
            valid[name] = value
            bucket = counts[name]
            bucket[value] = bucket.get(value, 0) + 1

        attr_values = _filled(row, sheet.attribute)
        host = valid.get(sheet.primary)
        if host is None:
            # 主列取值为空或被过滤：这行的属性无处可挂，整行丢弃计数。
            # 不做「向上填充上一个非空值」，那是臆造数据。
            if attr_values:
                report["attribute_dropped_no_primary"] += 1
        else:
            slot = attrs.setdefault(host, {})
            # 实体列的取值一并挂上：该列若因高基数被降级，它的值就正好是主列实体的属性
            for name, value in {**attr_values, **valid}.items():
                if name != sheet.primary:
                    slot.setdefault(name, value)

        for rel in sheet.rels:
            subject, object_ = valid.get(rel["s"]), valid.get(rel["o"])
            if not subject or not object_ or subject == object_:
                continue
            triples.setdefault((subject, rel["p"], object_), (rel["s"], rel["o"]))

    return counts, attrs, triples, rows_read


def _filled(row: Dict[str, Any], names: List[str]) -> Dict[str, str]:
    """本行在这些列上的非空取值"""
    filled: Dict[str, str] = {}
    for name in names:
        value = str(row.get(name) or "").strip()
        if value:
            filled[name] = value
    return filled


def _kept_columns(sheet: _Sheet, counts: Dict[str, Dict[str, int]],
                  report: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """按上限决定哪些实体列真能建实体（高列先降级，再判整表限流）"""
    kept: Dict[str, Dict[str, int]] = {}
    for name, values in counts.items():
        if not values:
            continue
        if len(values) > COLUMN_ENTITY_LIMIT:
            report["column_downgraded_high_cardinality"].append(f"{sheet.title}.{name}")
            continue
        kept[name] = values
    if not kept:
        return {}
    if sum(len(values) for values in kept.values()) > SHEET_ENTITY_LIMIT:
        report["sheet_entity_limit_hit"].append(sheet.title)
        # 限流时只保主列；③ 判不出主列时退到第一个实体列，好过整表不导入
        subject = sheet.primary or sheet.entity[0]
        return {subject: kept[subject]} if subject in kept else {}
    return kept


def _collect(sheet: _Sheet, kept: Dict[str, Dict[str, int]],
             attrs: Dict[str, Dict[str, str]],
             triples: Dict[Tuple[str, str, str], Tuple[str, str]],
             doc_name: str, domain: str,
             entities: Dict[str, Dict[str, Any]],
             relationships: Dict[Tuple[str, str, str], Dict[str, str]],
             report: Dict[str, Any]) -> None:
    """把保留下来的列装配成实体与边（跨 sheet 同名值合并为同一实体）"""
    if attrs and sheet.primary not in kept:
        # 主列被高基数降级或被整表限流挤掉：属性无处可挂，按不同主值数计入丢弃
        report["attribute_dropped_no_primary"] += len(attrs)
        attrs = {}

    kept_names = set(kept)
    # 有一列就叫 raw_type 时，词表外标记要用的键被真列名占了：列值让位。
    # 让位必须留痕 —— 降级证据静默消失比丢一个属性值难查得多。
    displaced = False

    for name, values in kept.items():
        type_key, raw_type = _column_type(sheet, name, domain)
        description = f"来自 {doc_name}/{sheet.title}.{name}"
        for value, count in values.items():
            # 只留下没建成实体的列值（被降级的实体列，或本来就是属性列）
            attributes = {key: value_ for key, value_ in attrs.get(value, {}).items()
                          if key not in kept_names}
            if raw_type:
                if attributes.pop(RAW_TYPE_KEY, None) is not None and not displaced:
                    displaced = True
                    report["attribute_key_reserved"].append(f"{sheet.title}.{RAW_TYPE_KEY}")
                attributes[RAW_TYPE_KEY] = raw_type
            _merge_entity(entities, value, type_key, description, count, attributes)

    for (subject, predicate, object_), (subject_col, object_col) in triples.items():
        if subject not in kept.get(subject_col, {}) or object_ not in kept.get(object_col, {}):
            report["rel_endpoint_dropped"] += 1
            continue
        relationships[(subject, predicate, object_)] = {
            "s": subject, "p": predicate, "o": object_}


def _column_type(sheet: _Sheet, name: str, domain: str) -> Tuple[str, str]:
    """列标注的实体类型写库前过本体校验 → (受控 key, 词表外原值)

    落库缝不替这里归一（文档侧实体类型历史上不做词表校验），所以④ 自己收口：
    词表外落 other，原值记在该实体 attributes 的 `RAW_TYPE_KEY`（节点没有这个属性，
    落库缝不加字段）。这个键是装配层保留的，真列名撞上它时列值让位并留痕。
    """
    from ontology.registry import ontology_registry

    raw = (sheet.types.get(name) or "").strip()
    if not raw:
        return "other", ""
    if ontology_registry.is_valid_object_type(raw, domain):
        return raw, ""
    logger.warning(f"[table_import] 实体类型词表外: {sheet.title}.{name} → {raw}，落 other")
    return "other", raw


def _merge_entity(entities: Dict[str, Dict[str, Any]], name: str, type_key: str,
                  description: str, count: int,
                  attributes: Dict[str, str]) -> None:
    """同名值合并：entity_id = MD5(name)，跨 sheet / 跨列的同一业务对象是一个节点

    类型先到先得（同名不同义是本方案的已知代价，靠 description 里的列出处人工辨认），
    属性与描述补空缺，出现次数取最大值 —— 与文档 LLM 分支的 dedupe 同口径。
    """
    existing = entities.get(name)
    if existing is None:
        entities[name] = {"n": name, "t": type_key, "c": count,
                          "d": description, "a": dict(attributes)}
        return
    if existing["t"] != type_key:
        logger.debug(f"[table_import] 同名实体类型不一致，保留 {existing['t']}: {name}")
    existing["c"] = max(existing["c"], count)
    if not existing["d"] and description:
        existing["d"] = description
    for key, value in attributes.items():
        existing["a"].setdefault(key, value)
