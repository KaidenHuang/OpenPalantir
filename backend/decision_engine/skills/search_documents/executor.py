"""文档搜索 Skill 执行器"""
def execute(params: dict) -> dict:
    from decision_engine.retrievers.document_summary_retriever import DocumentSummaryRetriever
    from decision_engine.contracts import AnalyzedQuery
    query = AnalyzedQuery(entities=[params.get("query", "")])
    retriever = DocumentSummaryRetriever()
    results = retriever.retrieve(query, {})
    limit = params.get("limit", 5)
    return {
        "documents": [
            {"source": r.source_id, "summary": r.content.get("summary", ""), "score": r.relevance_score}
            for r in results[:limit]
        ],
        "total": len(results),
    }