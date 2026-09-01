"""
实体搜索 Skill 执行器

在 Neo4j 知识图谱中全文搜索实体。
"""

def execute(params: dict) -> dict:
    from knowledge_graph.graph_manager import graph_manager

    query = params.get("query", "")
    entity_type = params.get("entity_type")
    limit = params.get("limit", 10)

    entity_types = [entity_type] if entity_type else None

    entities = graph_manager.search_entities(
        query=query,
        limit=limit,
        entity_types=entity_types,
    )

    return {
        "entities": [
            {
                "name": e.get("name", ""),
                "type": e.get("type", ""),
                "description": e.get("description", "") or "",
                "confidence": e.get("confidence", 0),
            }
            for e in entities
        ],
        "total": len(entities),
    }