"""中心性分析 Skill 执行器"""
def execute(params: dict) -> dict:
    from analysis_engine.analyzer import analyzer
    c_type = params.get("centrality_type")
    types = [c_type] if c_type else None
    max_nodes = params.get("max_nodes", 5000)
    result = analyzer.analyze_centrality(centrality_types=types, max_nodes=max_nodes)
    top_n = params.get("top_n", 10)
    # top_nodes_by_type 是 dict: {centrality_type: [node_list]}
    top_by_type = result.get("top_nodes_by_type", {})
    trimmed = {}
    for k, v in top_by_type.items():
        trimmed[k] = v[:top_n] if isinstance(v, list) else v
    return {"top_nodes": trimmed, "total_nodes": len(result.get("nodes", []))}