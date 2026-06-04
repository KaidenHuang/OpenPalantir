from abc import ABC, abstractmethod
from typing import Dict, List

from system.logger import logger
from decision_engine.contracts import (
    AnalyzedQuery, DecisionAnswer, DecisionRequest, EvidenceItem,
)
from decision_engine.query_analyzer import QueryAnalyzer
from decision_engine.retrieval_orchestrator import RetrievalOrchestrator
from decision_engine.evidence_fusion import EvidenceFusion
from decision_engine.context_builder import ContextBuilder
from decision_engine.llm_reasoner import LLMReasoner
from decision_engine.conversation_manager import conv_manager


class BaseDecisionPlugin(ABC):
    domain: str = "general"
    system_prompt_extra: str = ""

    def __init__(self):
        self.query_analyzer = QueryAnalyzer()
        self.retrieval_orch = RetrievalOrchestrator()
        self.evidence_fusion = EvidenceFusion()
        self.context_builder = ContextBuilder()
        self.llm_reasoner = LLMReasoner()
        self.conv_manager = conv_manager

    def run(self, request: DecisionRequest) -> dict:
        """Full RAG pipeline entry point."""
        logger.info(f"[plugin:{self.domain}] run question={request.question[:60]}")

        session_id = self.conv_manager.get_or_create(
            request.session_id, domain=self.domain)

        history = self.conv_manager.get_history(session_id)

        analyzed = self.query_analyzer.analyze(request.question, history)
        logger.info(f"[plugin:{self.domain}] intent={analyzed.intent}, sources={analyzed.required_sources}")
        logger.info(f"[plugin:{self.domain}] entities={analyzed.entities}, entity_types={analyzed.entity_types}")
        logger.info(f"[plugin:{self.domain}] sub_questions={analyzed.sub_questions}")

        context = {
            "question": request.question,
            "connection_id": request.connection_id,
            **request.context,
        }
        raw_evidence = self.retrieval_orch.retrieve(analyzed, context)

        evidence = self.evidence_fusion.fuse(raw_evidence, analyzed)
        logger.info(f"[plugin:{self.domain}] evidence fused count={len(evidence)} (entity={sum(1 for e in evidence if e.source_type=='entity')}, db_summary={sum(1 for e in evidence if e.source_type=='database_summary')}, doc_summary={sum(1 for e in evidence if e.source_type=='document_summary')}, relation={sum(1 for e in evidence if e.source_type=='graph_relation')})")

        structured_ctx = self.context_builder.build(
            question=request.question,
            evidence=evidence,
            domain=analyzed.domain,
            intent=analyzed.intent,
            history=history,
            sub_questions=analyzed.sub_questions,
        )

        answer = self.llm_reasoner.reason(structured_ctx)
        logger.info(f"[plugin:{self.domain}] answer work_orders={len(answer.work_orders)}")

        # Build citations (aggregated: DOC→document level, DBS→table level)
        seen: set = set()
        citations = []
        for e in evidence:
            if not e.citation:
                continue
            if e.source_type == "document_summary":
                key = ("doc", e.citation)
            elif e.source_type == "database_summary":
                if "table_name" not in e.payload:
                    continue  # skip db-level entries, keep only table-level
                key = ("dbs", e.citation)
            else:
                continue  # skip entity / graph_relation citations
            if key not in seen:
                seen.add(key)
                citations.append({
                    "citation": e.citation,
                    "source_type": e.source_type,
                    "source_id": e.source_name,
                })

        self.conv_manager.add_turn(
            session_id, request.question, analyzed, answer,
            evidence=evidence,
            evidence_citations=citations,
        )

        return {
            "domain": self.domain,
            "intent": analyzed.intent,
            "session_id": session_id,
            "analyzed_query": analyzed,
            "evidence": evidence,
            "evidence_citations": citations,
            "answer": answer,
            "metadata": {
                "plugin": self.domain,
                "history_depth": len(history),
                "token_estimate": structured_ctx.total_tokens_estimate,
            },
        }
