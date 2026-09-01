"""社区检测 Skill 执行器"""
def execute(params: dict) -> dict:
    from analysis_engine.analyzer import analyzer
    result = analyzer.analyze_community()
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