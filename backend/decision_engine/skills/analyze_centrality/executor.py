"""中心性分析 Skill 执行器"""
def execute(params: dict) -> dict:
    from analysis_engine.analyzer import analyzer
    c_type = params.get("centrality_type")
    types = [c_type] if c_type else None
    result = analyzer.analyze_centrality(centrality_types=types)
    top_n = params.get("top_n", 10)
    top_nodes = result.get("top_nodes", {})
    # 截取每种中心性的 top_n
    trimmed = {}
    for k, v in top_nodes.items():
        trimmed[k] = v[:top_n] if isinstance(v, list) else v
    return {"top_nodes": trimmed, "total_nodes": len(result.get("nodes", []))}