"""数据库导入辅助函数

从 task_manager.py 迁移的行级导入相关工具函数，
供 SchemaImportHandler 和 TaskManager 共用。
"""

from typing import Dict, List, Any, Optional
from system.logger import logger

_PRIMARY_KEY_MARKERS = ("PRI", "PRIMARY KEY", "PK")
_DEFAULT_ENTITY_TYPE = "其他"
_MAX_CROSS_PRODUCT_PAIRS = 50


def build_entity_name(table_name: str, row: Dict, pk_columns: List[str]) -> str:
    """构建行实体的规范名称 {table_name}:{pk_value1}:{pk_value2}...，PK 缺失时返回空字符串"""
    if not pk_columns or not row:
        return ""
    pk_values = []
    for pk in pk_columns:
        val = row.get(pk)
        if val is None or str(val) == "":
            return ""
        pk_values.append(str(val))
    return f"{table_name}:{':'.join(pk_values)}"


def detect_primary_keys(columns_by_table: Dict[str, List[Dict]]) -> Dict[str, List[str]]:
    pk_columns = {}
    for table_name, cols in columns_by_table.items():
        pk_cols = [c["column_name"] for c in cols if c.get("column_key") in _PRIMARY_KEY_MARKERS]
        if not pk_cols:
            first = cols[0]["column_name"] if cols else None
            if first:
                logger.warning(f"表 {table_name} 未检测到主键，使用首列 '{first}' 作为代理键")
                pk_cols = [first]
        pk_columns[table_name] = pk_cols
    return pk_columns


def refine_pks_via_dialect(pk_columns: Dict[str, List[str]], columns_by_table: Dict[str, List[Dict]],
                            dialect, connection, table_names: List[str]):
    """对于使用代理键的表，通过数据库 dialect 检测真实主键"""
    for full_name in table_names:
        if len(pk_columns.get(full_name, [])) != 1:
            continue
        try:
            real_pks = dialect.get_primary_key_columns(connection, full_name)
            if real_pks:
                pk_columns[full_name] = real_pks
                logger.info(f"表 {full_name} 通过 dialect 检测到主键: {real_pks}")
        except Exception:
            pass


def make_relationship(subject: str, object_: str, predicate: str, confidence: float = 0.8,
                       description: str = "", attributes: dict = None) -> Dict:
    return {
        "s": subject,
        "o": object_,
        "p": predicate,
        "ot": "",
        "d": description,
        "a": attributes or {}
    }


def get_fk_column_info(foreign_keys: List[Dict], inferred_relationships: List[Dict]) -> Dict[str, set]:
    """收集需要建立值索引的列：返回 {表名: {列名集合}}"""
    col_info: Dict[str, set] = {}
    for fk in foreign_keys:
        table = fk.get("table_name") or fk.get("TABLE_NAME", "")
        col = fk.get("column_name") or fk.get("COLUMN_NAME", "")
        if table and col:
            col_info.setdefault(table, set()).add(col)
    for rel in inferred_relationships:
        src_t = rel.get("source_table", "")
        src_c = rel.get("source_column", "")
        tgt_t = rel.get("target_table", "")
        tgt_c = rel.get("target_column", "")
        if src_t and src_c:
            col_info.setdefault(src_t, set()).add(src_c)
        if tgt_t and tgt_c:
            col_info.setdefault(tgt_t, set()).add(tgt_c)
    return col_info


def extract_pk_value(row: Dict, pk_columns: List[str]) -> Optional[str]:
    """从行数据中提取 PK 值字符串，多列用 : 连接，无法提取时返回 None"""
    values = []
    for pk in pk_columns:
        val = row.get(pk)
        if val is None or str(val) == "":
            return None
        values.append(str(val))
    return ":".join(values)


def build_entities_batch(rows: List[Dict], table_name: str, entity_type: str,
                          pk_columns: List[str], db_prefix: str) -> List[Dict]:
    """为一批行构建实体字典列表，行数据列值映射为 attributes"""
    entities = []
    for row in rows:
        entity_name = build_entity_name(table_name, row, pk_columns)
        if not entity_name:
            continue
        # 列值映射为结构化 attributes（保留原始类型）
        attributes = {}
        for col, val in row.items():
            if val is not None:
                attributes[col] = val
        # 自动选择 byname：优先选含 "name" 的非主键字符串列，否则取第一个非主键字符串值
        byname = None
        pk_set = set(pk_columns)
        name_candidates = []
        for col, val in row.items():
            if val is not None and isinstance(val, str) and col not in pk_set:
                if "name" in col.lower():
                    byname = val
                    break
                name_candidates.append(val)
        if byname is None and name_candidates:
            byname = name_candidates[0]
        # description 取简要的主键描述
        pk_desc = ", ".join(f"{pk}={row.get(pk, '')}" for pk in pk_columns)
        entities.append({
            "n": entity_name,
            "t": entity_type,
            "bn": byname,
            "c": 1,
            "datasource": f"{db_prefix}/{table_name}",
            "d": f"{table_name}({pk_desc})",
            "a": attributes
        })
    return entities


def dedup_relationships(relationships: List[Dict]) -> List[Dict]:
    """去重关系列表，保留首次出现的 (subject, predicate, object) 三元组"""
    seen: set = set()
    deduped = []
    for rel in relationships:
        key = (rel.get("s", ""), rel.get("p", ""), rel.get("o", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(rel)
    skipped = len(relationships) - len(deduped)
    if skipped:
        logger.info(f"关系去重: 移除了 {skipped} 条重复关系")
    return deduped


def build_relationships_from_index(foreign_keys: List[Dict], inferred_relationships: List[Dict],
                                    pk_index: Dict[str, Dict[str, str]],
                                    fk_index: Dict[str, Dict[str, Dict[str, str]]],
                                    max_cross_product_pairs: int = 50,
                                    skip_tables: set = None) -> List[Dict]:
    """使用 PK/FK 索引构建关系，无需完整行数据

    Args:
        skip_tables: 跳过这些表的 FK 关系（junction/attribute 表已有专门处理路径）
    """
    relationships = []
    skip = skip_tables or set()

    for fk in foreign_keys:
        source_table = fk.get("table_name") or fk.get("TABLE_NAME", "")
        if source_table in skip:
            continue
        source_column = fk.get("column_name") or fk.get("COLUMN_NAME", "")
        target_table = fk.get("referenced_table_name") or fk.get("REFERENCED_TABLE_NAME", "")

        source_fk_idx = fk_index.get(source_table, {}).get(source_column, {})
        target_pk_idx = pk_index.get(target_table, {})

        for fk_value, source_entity in source_fk_idx.items():
            target_entity = target_pk_idx.get(fk_value)
            if not target_entity:
                continue
            desc = f"{source_table}.{source_column}={fk_value} -> {target_table}"
            relationships.append(
                make_relationship(source_entity, target_entity, "Foreign key", 1.0, desc)
            )

    for rel in inferred_relationships:
        source_table = rel.get("source_table", "")
        target_table = rel.get("target_table", "")
        src_col = rel.get("source_column", "")
        tgt_col = rel.get("target_column", "")
        pred = rel.get("relationship_type", "Related to")
        confidence = rel.get("confidence", 0.8)
        rel_desc = rel.get("description", "")

        if src_col and tgt_col:
            src_idx = fk_index.get(source_table, {}).get(src_col, {})
            tgt_idx = fk_index.get(target_table, {}).get(tgt_col, {})
            if not src_idx or not tgt_idx:
                continue
            common = set(src_idx.keys()) & set(tgt_idx.keys())
            for val in common:
                s_entity = src_idx[val]
                t_entity = tgt_idx[val]
                relationships.append(
                    make_relationship(s_entity, t_entity, pred, confidence, rel_desc)
                )
        else:
            src_pk = pk_index.get(source_table, {})
            tgt_pk = pk_index.get(target_table, {})
            if len(src_pk) * len(tgt_pk) > max_cross_product_pairs:
                logger.warning(f"跳过推断关系 {source_table}->{target_table}: "
                               f"行对过多 ({len(src_pk)}x{len(tgt_pk)})")
                continue
            for s_entity in src_pk.values():
                for t_entity in tgt_pk.values():
                    relationships.append(
                        make_relationship(s_entity, t_entity, pred, confidence, rel_desc)
                    )

    if relationships:
        relationships = dedup_relationships(relationships)
    return relationships


# ── 表角色分类与非实体表处理 ──


def classify_tables_by_role(
    tables: List[Dict],
    pk_columns: Dict[str, List[str]],
    foreign_keys: List[Dict],
    columns_by_table: Dict[str, List[Dict]],
) -> Dict[str, str]:
    """根据 table_role 分类所有表，返回 {table_name: role}

    优先级：
    1. LLM 标注的 table_role（Phase 1 已标注）
    2. 结构启发式兜底（LLM 未标注或标注异常时）
    """
    # 按 table_name 分组 FK
    fk_by_table: Dict[str, List[Dict]] = {}
    for fk in foreign_keys:
        table = fk.get("table_name") or fk.get("TABLE_NAME", "")
        if table:
            fk_by_table.setdefault(table, []).append(fk)

    # 收集被 FK 引用的表集合（用于 attribute 表判定）
    referenced_tables = set()
    for fk in foreign_keys:
        ref = fk.get("referenced_table_name") or fk.get("REFERENCED_TABLE_NAME", "")
        if ref:
            referenced_tables.add(ref)

    role_map: Dict[str, str] = {}
    for table_info in tables:
        name = table_info.get("table_name", "")
        if not name:
            continue

        # 1. 优先使用 LLM 标注
        llm_role = table_info.get("table_role", "")
        if llm_role in ("entity", "junction", "attribute"):
            role_map[name] = llm_role
            continue

        # 2. 结构启发式兜底
        pks = set(pk_columns.get(name, []))
        fks = fk_by_table.get(name, [])
        fk_cols = set(fk.get("column_name") or fk.get("COLUMN_NAME", "") for fk in fks)
        ref_tables = set(
            fk.get("referenced_table_name") or fk.get("REFERENCED_TABLE_NAME", "")
            for fk in fks
        )
        all_cols = set(c["column_name"] for c in columns_by_table.get(name, []))
        non_fk_cols = all_cols - fk_cols

        # junction: PK 全为 FK 且引用 >= 2 个不同表
        if (pks and len(pks) >= 2
                and pks.issubset(fk_cols)
                and len(ref_tables) >= 2):
            role_map[name] = "junction"
            logger.info(f"表 {name} 通过启发式识别为 junction（关联表）")
            continue

        # attribute: 仅有 1 个 FK 指向实体表，且非 FK 列较少，自身不被其他表引用
        if (len(fks) == 1
                and len(ref_tables) == 1
                and name not in referenced_tables
                and len(non_fk_cols) <= 5):
            role_map[name] = "attribute"
            logger.info(f"表 {name} 通过启发式识别为 attribute（属性表）")
            continue

        role_map[name] = "entity"

    # 日志统计
    counts = {"entity": 0, "junction": 0, "attribute": 0}
    for role in role_map.values():
        counts[role] = counts.get(role, 0) + 1
    logger.info(
        f"表角色分类完成: 共 {len(role_map)} 个表 "
        f"(entity={counts['entity']}, junction={counts['junction']}, attribute={counts['attribute']})"
    )
    return role_map


def build_junction_relationships(
    junction_tables: List[str],
    junction_row_data: Dict[str, List[Dict]],
    fk_defs_by_table: Dict[str, List[Dict]],
    pk_index: Dict[str, Dict[str, str]],
) -> List[Dict]:
    """关联表每行 → 被引用实体间的直接关系边

    例：dept_emp(emp_no=10001, dept_no=d005, from_date=..., to_date=...)
    → employees:10001 --[dept_emp {from_date, to_date}]--> departments:d005
    """
    relationships = []

    for jt_name in junction_tables:
        fks = fk_defs_by_table.get(jt_name, [])
        if len(fks) < 2:
            continue

        # 提取 FK 列名和引用的目标表
        fk_info = []
        fk_col_names = set()
        for fk in fks:
            col = fk.get("column_name") or fk.get("COLUMN_NAME", "")
            ref_table = fk.get("referenced_table_name") or fk.get("REFERENCED_TABLE_NAME", "")
            if col and ref_table:
                fk_info.append({"col": col, "ref_table": ref_table})
                fk_col_names.add(col)

        if len(fk_info) < 2:
            continue

        rows = junction_row_data.get(jt_name, [])
        for row in rows:
            # 解析每行的 FK 值 → 目标实体名
            entities_in_row = []
            for fi in fk_info:
                fk_val = row.get(fi["col"])
                if fk_val is None or str(fk_val).strip() == "" or str(fk_val) == "None":
                    continue
                target_entity = pk_index.get(fi["ref_table"], {}).get(str(fk_val))
                if target_entity:
                    entities_in_row.append((fi["ref_table"], target_entity))

            if len(entities_in_row) < 2:
                continue

            # 非 FK 列作为关系属性
            attrs = {k: v for k, v in row.items()
                     if k not in fk_col_names and v is not None}

            # 为每对 (A, B) 创建单向关系 A→B（避免双向重复）
            for i in range(len(entities_in_row)):
                for j in range(i + 1, len(entities_in_row)):
                    src_table, src_entity = entities_in_row[i]
                    tgt_table, tgt_entity = entities_in_row[j]
                    desc = f"{jt_name}: {src_entity} -> {tgt_entity}"
                    relationships.append(
                        make_relationship(src_entity, tgt_entity, jt_name, 1.0, desc, attrs)
                    )

    if relationships:
        relationships = dedup_relationships(relationships)
    return relationships


def collect_attribute_data(
    attribute_tables: List[str],
    attribute_row_data: Dict[str, List[Dict]],
    fk_defs_by_table: Dict[str, List[Dict]],
    pk_index: Dict[str, Dict[str, str]],
) -> Dict[str, Dict[str, List[Dict]]]:
    """属性表行 → 按父实体分组，返回 {parent_entity_name: {table_name: [rows]}}

    例：titles(emp_no=10001, title=Engineer, from_date=..., to_date=...)
    → {"employees:10001": {"titles": [{"title": "Engineer", "from_date": ..., "to_date": ...}]}}
    """
    result: Dict[str, Dict[str, List[Dict]]] = {}

    for at_name in attribute_tables:
        fks = fk_defs_by_table.get(at_name, [])
        if len(fks) != 1:
            continue

        fk = fks[0]
        fk_col = fk.get("column_name") or fk.get("COLUMN_NAME", "")
        ref_table = fk.get("referenced_table_name") or fk.get("REFERENCED_TABLE_NAME", "")
        if not fk_col or not ref_table:
            continue

        # 收集 FK 列名（含复合主键中的非 FK 列也不排除，只去掉外键列本身）
        rows = attribute_row_data.get(at_name, [])
        for row in rows:
            fk_val = row.get(fk_col)
            if fk_val is None or str(fk_val).strip() == "" or str(fk_val) == "None":
                continue

            parent_entity = pk_index.get(ref_table, {}).get(str(fk_val))
            if not parent_entity:
                continue

            # 去掉 FK 列，剩余列作为属性记录
            attr_record = {k: v for k, v in row.items()
                          if k != fk_col and v is not None}
            if not attr_record:
                continue

            result.setdefault(parent_entity, {}).setdefault(at_name, []).append(attr_record)

    return result
