from abc import ABC, abstractmethod
from enum import Enum
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
from decision_engine.memory.memory_manager import memory_manager
from decision_engine.memory.memory_extractor import MemoryExtractor


class DecisionMode(str, Enum):
    RAG_PIPELINE = "rag_pipeline"       # 现有固定 RAG 管道（默认）
    SKILL_REASONING = "skill_reasoning"  # Skill 多轮推理


class BaseDecisionPlugin(ABC):
    domain: str = "general"
    system_prompt_extra: str = ""
    decision_mode: DecisionMode = DecisionMode.RAG_PIPELINE

    def __init__(self):
        self.query_analyzer = QueryAnalyzer()
        self.retrieval_orch = RetrievalOrchestrator()
        self.evidence_fusion = EvidenceFusion()
        self.context_builder = ContextBuilder()
        self.llm_reasoner = LLMReasoner()
        self.conv_manager = conv_manager
        self._skill_reasoner = None
        self._memory_extractor = MemoryExtractor()

    @property
    def skill_reasoner(self):
        if self._skill_reasoner is None:
            from decision_engine.tool_manager.tool_reasoner import ToolReasoner
            from decision_engine.tool_manager.skill.skill_registry import skill_registry
            self._skill_reasoner = ToolReasoner(skill_registry)
        return self._skill_reasoner

    def run(self, request: DecisionRequest) -> dict:
        """决策入口：分发到 RAG 管道或 Skill 推理"""
        if self.decision_mode == DecisionMode.SKILL_REASONING:
            return self._run_skill_mode(request)
        return self._run_rag_mode(request)

    def _inject_memories(self, request: DecisionRequest):
        """检索短期/长期记忆并注入到请求上下文"""
        try:
            session_id = request.session_id or ""
            domain = self.domain

            # 短期记忆检索
            short_term = memory_manager.retrieve_short_term(
                query=request.question, domain=domain, limit=5
            )
            if short_term:
                request.context["short_term_memories"] = short_term
                logger.info(
                    f"[plugin:{domain}] 短期记忆注入: {len(short_term)}条"
                )

            # 长期记忆（hash 去重）
            long_term = memory_manager.read_long_term_memories()
            if long_term and (long_term.get("preferences") or
                              long_term.get("decisions")):
                # 从已读取的内容计算 hash，避免二次读取文件
                import hashlib
                import json
                current_hash = hashlib.md5(
                    json.dumps(long_term, ensure_ascii=False).encode()
                ).hexdigest()
                session = self.conv_manager.get_session(session_id)
                if session and current_hash != session.long_term_memory_hash:
                    request.context["long_term_memories"] = long_term
                    session.long_term_memory_hash = current_hash
                    self.conv_manager.save_session(session)
                    logger.info(
                        f"[plugin:{domain}] 长期记忆注入: "
                        f"偏好={len(long_term.get('preferences', []))}条, "
                        f"决策={len(long_term.get('decisions', []))}条"
                    )
        except Exception as e:
            logger.error(f"[plugin:{self.domain}] 记忆注入失败: {e}")

    def _extract_memories_async(self, session_id: str, question: str,
                                answer, domain: str):
        """异步提取本轮对话的记忆"""
        try:
            summary = answer.summary or answer.situation_analysis or ""
            self._memory_extractor.extract_async(
                question=question,
                answer_summary=summary,
                session_id=session_id,
                domain=domain,
            )
        except Exception as e:
            logger.error(f"[plugin:{self.domain}] 记忆提取调度失败: {e}")

    def _build_simple_response(self, request: DecisionRequest,
                               analyzed: AnalyzedQuery, session_id: str) -> dict:
        """为简单问题（问候/身份/能力/告别/感谢）构建快速响应，跳过检索和推理"""
        answer = DecisionAnswer(
            summary=analyzed.direct_answer,
            situation_analysis=analyzed.direct_answer,
        )
        self.conv_manager.add_turn(
            session_id, request.question, analyzed, answer,
            response_type="simple",
        )
        logger.info(f"[plugin:{self.domain}] simple_response intent={analyzed.intent}")
        return {
            "domain": self.domain,
            "intent": analyzed.intent,
            "session_id": session_id,
            "analyzed_query": analyzed,
            "evidence": [],
            "evidence_citations": [],
            "answer": answer,
            "response_type": "simple",
            "metadata": {"plugin": self.domain},
        }

    def _build_no_data_response(self, request: DecisionRequest,
                                analyzed: AnalyzedQuery, session_id: str,
                                history: list) -> dict:
        """检索证据为空时，跳过 LLM 推理，直接返回友好提示"""
        answer = DecisionAnswer(
            summary=f"在当前知识库中未找到与「{request.question}」直接相关的数据。\n\n"
                    f"建议：\n"
                    f"- 确认已导入相关文档或数据库\n"
                    f"- 尝试用更具体的关键词重新提问\n"
                    f"- 在「图谱可视化」页面查看已有数据范围",
            situation_analysis=f"未找到与「{request.question}」相关的数据。",
        )
        self.conv_manager.add_turn(
            session_id, request.question, analyzed, answer,
            response_type="no_data",
        )
        # 无数据时仍提取记忆（用户问题本身可能揭示偏好或关注领域）
        self._extract_memories_async(
            session_id, request.question, answer, self.domain)
        logger.info(f"[plugin:{self.domain}] no_data_response")
        return {
            "domain": self.domain,
            "intent": analyzed.intent,
            "session_id": session_id,
            "analyzed_query": analyzed,
            "evidence": [],
            "evidence_citations": [],
            "answer": answer,
            "response_type": "no_data",
            "metadata": {
                "plugin": self.domain,
                "history_depth": len(history),
            },
        }

    def _run_rag_mode(self, request: DecisionRequest) -> dict:
        """完整 RAG 管道"""
        logger.info(f"[plugin:{self.domain}] run question={request.question[:60]}")

        session_id = self.conv_manager.get_or_create(
            request.session_id, domain=self.domain)

        # 注入记忆上下文（需要在 get_or_create 之后，确保 session 存在）
        self._inject_memories(request)

        history = self.conv_manager.get_history(session_id, max_turns=3)

        analyzed = self.query_analyzer.analyze(request.question, history)
        logger.info(f"[plugin:{self.domain}] intent={analyzed.intent}, sources={analyzed.required_sources}")

        # 简单问题快速出口：QueryAnalyzer 已识别并生成直接回答
        SIMPLE_INTENTS = {"greeting", "identity", "capability", "farewell", "thanks"}
        SIMPLE_DEFAULTS = {
            "greeting": "您好！我是智能决策助手，请问有什么可以帮您的？",
            "identity": "我是智能决策助手，专注于数据分析和决策支持。",
            "capability": "我可以帮您分析知识图谱、检索文档和数据库、提供决策建议和行动方案。请问您想了解什么？",
            "farewell": "再见！如有需要随时找我。",
            "thanks": "不客气！如有其他问题，随时告诉我。",
        }
        if analyzed.intent in SIMPLE_INTENTS:
            if not analyzed.direct_answer:
                analyzed.direct_answer = SIMPLE_DEFAULTS.get(analyzed.intent, "")
            return self._build_simple_response(request, analyzed, session_id)

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

        # 无数据快速出口：检索证据为空时跳过 LLM 推理
        if not evidence:
            return self._build_no_data_response(request, analyzed, session_id, history)

        structured_ctx = self.context_builder.build(
            question=request.question,
            evidence=evidence,
            domain=analyzed.domain,
            intent=analyzed.intent,
            history=history,
            sub_questions=analyzed.sub_questions,
            short_term_memories=request.context.get("short_term_memories"),
            long_term_memories=request.context.get("long_term_memories"),
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

        # 异步提取记忆
        self._extract_memories_async(session_id, request.question, answer, self.domain)

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

    def _run_skill_mode(self, request: DecisionRequest) -> dict:
        """Skill 多轮推理模式"""
        logger.info(f"[plugin:{self.domain}] skill_mode question={request.question[:60]}")

        session_id = self.conv_manager.get_or_create(
            request.session_id, domain=self.domain)
        history = self.conv_manager.get_history(session_id, max_turns=3)

        # 轻量意图分析（复用 QueryAnalyzer）
        analyzed = self.query_analyzer.analyze(request.question, history)
        logger.info(f"[plugin:{self.domain}] intent={analyzed.intent}, entities={analyzed.entities}")

        # 构建初始上下文
        initial_context = {
            "question": request.question,
            "domain": self.domain,
            "intent": analyzed.intent,
            "entities": analyzed.entities,
            "entity_types": analyzed.entity_types,
        }

        # 执行多轮工具推理
        result = self.skill_reasoner.reason(
            question=request.question,
            domain=self.domain,
            initial_context=initial_context,
        )

        self.conv_manager.add_turn(
            session_id, request.question, analyzed, result.answer,
            evidence=[],
            evidence_citations=[],
        )

        # 异步提取记忆
        self._extract_memories_async(session_id, request.question, result.answer, self.domain)

        return {
            "domain": self.domain,
            "intent": analyzed.intent,
            "session_id": session_id,
            "analyzed_query": analyzed,
            "evidence": [],
            "evidence_citations": [],
            "answer": result.answer,
            "skill_trace": [t.model_dump() for t in result.tool_traces],
            "decision_mode": "skill_reasoning",
            "metadata": {
                "plugin": self.domain,
                "history_depth": len(history),
                "tool_calls": result.total_tool_calls,
                "reasoning_turns": result.total_turns,
                "total_time_ms": result.total_time_ms,
            },
        }
