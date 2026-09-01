"""路径分析 Skill 执行器"""
def execute(params: dict) -> dict:
    from analysis_engine.analyzer import analyzer
    result = analyzer.analyze_path(
        source_entity=params.get("source_entity", ""),
        target_entity=params.get("target_entity", ""),
        k=params.get("k", 1),
    )
    return result