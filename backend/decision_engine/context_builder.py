from typing import Dict, List

from decision_engine.contracts import EvidenceItem, StructuredContext


class ContextBuilder:
    def build(self, question: str, evidence: List[EvidenceItem],
              domain: str, intent: str, history: List[Dict] = None,
              sub_questions: List[str] = None) -> StructuredContext:
        doc_ctx: List[EvidenceItem] = []
        db_ctx: List[EvidenceItem] = []
        entity_ctx: List[EvidenceItem] = []
        graph_ctx: List[EvidenceItem] = []

        for item in evidence:
            if item.source_type == "document_summary":
                doc_ctx.append(item)
            elif item.source_type == "database_summary":
                db_ctx.append(item)
            elif item.source_type == "entity":
                entity_ctx.append(item)
            elif item.source_type == "graph_relation":
                graph_ctx.append(item)

        total_chars = sum(len(e.summary) for e in evidence)

        return StructuredContext(
            question=question,
            history=history or [],
            domain=domain,
            intent=intent,
            sub_questions=sub_questions or [],
            document_context=doc_ctx,
            database_context=db_ctx,
            entity_context=entity_ctx,
            graph_context=graph_ctx,
            total_tokens_estimate=total_chars // 4,
        )
