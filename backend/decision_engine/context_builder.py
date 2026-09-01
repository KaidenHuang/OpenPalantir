from typing import Dict, List

from decision_engine.contracts import EvidenceItem, StructuredContext


class ContextBuilder:
    def build(self, question: str, evidence: List[EvidenceItem],
              domain: str, intent: str, history: List[Dict] = None,
              sub_questions: List[str] = None,
              short_term_memories: List[dict] = None,
              long_term_memories: dict = None) -> StructuredContext:
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

        # 格式化记忆
        memory_section = self._format_memories(
            short_term_memories or [], long_term_memories or {}
        )

        total_chars = sum(len(e.summary) for e in evidence)
        total_chars += len(memory_section)

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
            memory_context=memory_section,
            total_tokens_estimate=total_chars // 4,
        )

    @staticmethod
    def _format_memories(short_term: list, long_term: dict) -> str:
        """格式化记忆为 prompt 片段"""
        parts = []

        if long_term:
            prefs = long_term.get("preferences", [])
            decs = long_term.get("decisions", [])
            if prefs:
                parts.append(
                    "## 用户偏好\n" +
                    "\n".join(f"- {p}" for p in prefs)
                )
            if decs:
                parts.append(
                    "## 历史重要决策\n" +
                    "\n".join(f"- {d}" for d in decs)
                )

        if short_term:
            items = []
            for m in short_term:
                cat = m.get("category", "fact")
                content = m.get("content", "")
                if len(content) > 50:
                    content = content[:50]
                items.append(f"- [{cat}] {content}")
            parts.append(
                "## 近期相关记忆\n" + "\n".join(items[:5])
            )

        return "\n\n".join(parts)