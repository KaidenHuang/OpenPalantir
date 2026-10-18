"""
谓词归一化 + Cypher 关系类型安全插值 — 图谱写路径共用

所有关系写入点（relationship_repository / data_store / cdc / schema_import）
必须先经 normalize_predicate 归一为受控 LinkType key，再计算 relationship_id，
保证 relationship_id = MD5(subject_受控谓词_object) 全链一致。
"""
from typing import Tuple

from models.ids import compute_relationship_id

from .registry import OntologyError, ontology_registry

FALLBACK_PREDICATE = "其他"


def normalize_predicate(raw: str) -> Tuple[str, bool]:
    """任意谓词文本 → (受控 key, 是否命中词表)；未命中兜底为 FALLBACK_PREDICATE"""
    key = ontology_registry.resolve_predicate_any(raw)
    if key:
        return key, True
    return FALLBACK_PREDICATE, False


def canonical_rel_id(subject: str, raw_predicate: str, object_: str
                     ) -> Tuple[str, str, bool]:
    """归一化谓词并计算 relationship_id，返回 (rel_id, 受控 key, 是否命中词表)"""
    key, hit = normalize_predicate(raw_predicate)
    return compute_relationship_id(subject, key, object_), key, hit


def cypher_rel_type(predicate_key: str) -> str:
    """受控 key → Cypher 反引号类型名；非词表值拒绝（防注入）"""
    if not predicate_key or "`" in predicate_key:
        raise OntologyError(f"非法关系类型名: {predicate_key!r}")
    if not ontology_registry.is_link_key(predicate_key):
        raise OntologyError(f"关系类型 {predicate_key!r} 不在受控词表")
    return f"`{predicate_key}`"
