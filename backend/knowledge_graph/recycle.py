"""来源回收 — 某数据源全部图谱产出的组合回收入口

顺序语义（先边后实体）：摘除本来源对边的佐证，再摘实体佐证；
被其他来源佐证的产出保留，佐证清空的边/实体删除。
Cypher 片段一律来自 source_scope（语义在两个 repository 内）。
"""
from typing import Dict

from knowledge_graph.entity_repository import entity_repo
from knowledge_graph.relationship_repository import rel_repo


def recycle_datasource(datasource_prefix: str, defer_cache: bool = False) -> Dict[str, int]:
    """回收某来源的全部产出：先摘边佐证，再摘实体佐证（佐证清空即删）"""
    edges = rel_repo.recycle_datasource(datasource_prefix, defer_cache=defer_cache)
    entities = entity_repo.recycle_datasource(datasource_prefix, defer_cache=defer_cache)
    return {"edges": edges, "entities": entities}
