"""社区检测 Skill 执行器"""
def execute(params: dict) -> dict:
    from analysis_engine.analyzer import analyzer
    max_nodes = params.get("max_nodes", 5000)
    result = analyzer.analyze_community(max_nodes=max_nodes)
    communities = result.get("communities", [])
    return {
        "total_communities": result.get("total_communities", 0),
        "communities": [
            {
                "id": c.get("community_id", ""),
                "size": c.get("size", 0),
                "key_entities": (c.get("key_entities") or [])[:5],
            }
            for c in communities[:10]
        ],
    }