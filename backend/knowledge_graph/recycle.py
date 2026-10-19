"""来源回收 — 某数据源全部图谱产出的组合回收入口

顺序语义（先边后实体）：摘除本来源对边的佐证，再摘实体佐证；
被其他来源佐证的产出保留，佐证清空的边/实体删除。
Cypher 片段一律来自 source_scope（语义在两个 repository 内）。
"""
from typing import Dict

from knowledge_graph.entity_repository import entity_repo
from knowledge_graph.relationship_repository import rel_repo


def recycle_datasource(datasource_prefix: str, defer_cache: bool = False,
                       keep_hash: str = None) -> Dict[str, int]:
    """回收某来源的全部产出：先摘边佐证，再摘实体佐证（佐证清空即删）

    keep_hash（代际回收）：见 entity_repo/rel_repo.recycle_datasource——
    文档刷新场景只摘本来源旧代佐证，保留新代（URI@keep_hash）。
    """
    edges = rel_repo.recycle_datasource(datasource_prefix, defer_cache=defer_cache,
                                        keep_hash=keep_hash)
    entities = entity_repo.recycle_datasource(datasource_prefix, defer_cache=defer_cache,
                                              keep_hash=keep_hash)
    return {"edges": edges, "entities": entities}
