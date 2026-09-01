"""数据库概要查询 Skill 执行器"""
def execute(params: dict) -> dict:
    from decision_engine.retrievers.database_summary_retriever import DatabaseSummaryRetriever
    from decision_engine.contracts import AnalyzedQuery
    query = AnalyzedQuery(entities=[params.get("table_query", "")])
    retriever = DatabaseSummaryRetriever()
    results = retriever.retrieve(query, {})
    limit = params.get("limit", 5)
    return {
        "tables": [
            {"table": r.metadata.get("table", ""), "summary": r.content.get("summary", ""),
             "row_count": r.content.get("row_count", 0), "score": r.relevance_score}
            for r in results[:limit]
        ],
        "total": len(results),
    }