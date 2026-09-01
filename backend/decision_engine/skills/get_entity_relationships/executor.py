"""实体关系查询 Skill 执行器"""
def execute(params: dict) -> dict:
    from knowledge_graph.graph_manager import graph_manager
    entity_name = params.get("entity_name", "")
    entities = graph_manager.search_entities(query=entity_name, limit=1)
    if not entities:
        return {"found": False, "message": f"未找到实体 '{entity_name}'"}
    entity_id = entities[0].get("id", "")
    rels = graph_manager.get_entity_relationships(entity_id) if entity_id else []
    return {"entity_name": entity_name, "total_relations": len(rels), "relations": rels[:50]}