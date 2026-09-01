"""
实体详情 Skill 执行器

获取指定实体的详细信息。
"""

def execute(params: dict) -> dict:
    from knowledge_graph.graph_manager import graph_manager

    entity_name = params.get("entity_name", "")
    entities = graph_manager.search_entities(query=entity_name, limit=1)

    if not entities:
        return {"found": False, "message": f"未找到实体 '{entity_name}'"}

    entity = entities[0]
    entity_id = entity.get("id", "")

    rels = graph_manager.get_entity_relationships(entity_id) if entity_id else []

    return {
        "found": True,
        "entity": {
            "name": entity.get("name", ""),
            "type": entity.get("type", ""),
            "description": entity.get("description", "") or "",
            "datasource": entity.get("datasource", "") or "",
            "confidence": entity.get("confidence", 0),
        },
        "relationship_count": len(rels),
        "recent_relationships": [
            {
                "subject": r.get("subject", ""),
                "predicate": r.get("predicate", ""),
                "object": r.get("object", ""),
            }
            for r in rels[:20]
        ],
    }