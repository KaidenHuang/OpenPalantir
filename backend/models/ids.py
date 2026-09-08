"""
统一的 ID 生成函数

实体和关系的确定性 ID 集中管理，避免散落在多处导致不一致。
- entity_id = MD5(name)
- relationship_id = MD5(subject_predicate_object)
"""
import hashlib


def compute_entity_id(name: str) -> str:
    """确定性实体 ID：MD5(entity_name)"""
    return hashlib.md5(name.encode()).hexdigest()


def compute_relationship_id(subject: str, predicate: str, object_: str) -> str:
    """确定性关系 ID：MD5(subject_predicate_object)"""
    return hashlib.md5(f"{subject}_{predicate}_{object_}".encode()).hexdigest()
