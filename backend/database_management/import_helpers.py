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
                       description: str = "") -> Dict:
    return {
        "s": subject,
        "o": object_,
        "p": predicate,
        "ot": "",
        "d": description
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
        # description 取简要的主键描述
        pk_desc = ", ".join(f"{pk}={row.get(pk, '')}" for pk in pk_columns)
        entities.append({
            "n": entity_name,
            "t": entity_type,
            "bn": None,
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
                                    max_cross_product_pairs: int = 50) -> List[Dict]:
    """使用 PK/FK 索引构建关系，无需完整行数据"""
    relationships = []

    for fk in foreign_keys:
        source_table = fk.get("table_name") or fk.get("TABLE_NAME", "")
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
