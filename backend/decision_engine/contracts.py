import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from system.logger import logger


class AnalyzedQuery(BaseModel):
    domain: str = "general"
    intent: str = ""
    entities: List[str] = Field(default_factory=list)
    entity_types: Dict[str, str] = Field(default_factory=dict)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    required_sources: List[str] = Field(default_factory=list)
    sub_questions: List[str] = Field(default_factory=list)
    reasoning: str = ""


class RawEvidence(BaseModel):
    source_type: str
    source_id: str
    content: Dict[str, Any] = Field(default_factory=dict)
    relevance_score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvidenceItem(BaseModel):
    evidence_id: str
    source_type: str = ""
    source_name: str = ""
    summary: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    relevance_score: float = 0.0
    citation: str = ""


class EvidenceCitation(BaseModel):
    citation: str
    source_type: str
    source_id: str


class StructuredContext(BaseModel):
    question: str
    history: List[Dict[str, Any]] = Field(default_factory=list)
    domain: str = ""
    intent: str = ""
    sub_questions: List[str] = Field(default_factory=list)
    document_context: List[EvidenceItem] = Field(default_factory=list)
    database_context: List[EvidenceItem] = Field(default_factory=list)
    entity_context: List[EvidenceItem] = Field(default_factory=list)
    graph_context: List[EvidenceItem] = Field(default_factory=list)
    memory_context: str = ""  # 格式化的记忆片段，注入 prompt
    total_tokens_estimate: int = 0


class WorkOrder(BaseModel):
    title: str
    priority: str = "P2"
    owner_role: str = ""
    due_hint: str = ""
    steps: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DecisionAnswer(BaseModel):
    summary: str = ""
    situation_analysis: str = ""
    key_issues: List[Dict[str, Any]] = Field(default_factory=list)
    options: List[Dict[str, Any]] = Field(default_factory=list)
    recommendation: str = ""
    work_orders: List[WorkOrder] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "DecisionAnswer":
        """从 LLM 返回的 dict 解析 DecisionAnswer（LLMReasoner 和 ToolReasoner 共用）"""
        work_orders = []
        for wo in data.get("work_orders", []):
            if isinstance(wo, dict):
                work_orders.append(WorkOrder(**wo))
            else:
                logger.warning(f"[decision_answer] 跳过非 dict 类型的 work_order: {type(wo).__name__}")

        rec = data.get("recommendation", "")
        if isinstance(rec, dict):
            rec = json.dumps(rec, ensure_ascii=False)

        situation = data.get("situation_analysis", "")
        if isinstance(situation, dict):
            situation = json.dumps(situation, ensure_ascii=False)

        return cls(
            summary=str(data.get("summary", situation))[:500],
            situation_analysis=situation,
            key_issues=data.get("key_issues", []),
            options=data.get("options", []),
            recommendation=rec,
            work_orders=work_orders,
        )


class ToolTrace(BaseModel):
    """单次工具调用的执行记录"""
    step: int = 0
    skill_name: str = ""
    params: Dict[str, Any] = Field(default_factory=dict)
    result_summary: str = ""
    success: bool = True
    execution_time_ms: float = 0.0


class ConversationTurn(BaseModel):
    turn_id: str
    question: str
    analyzed_query: AnalyzedQuery = Field(default_factory=AnalyzedQuery)
    answer: DecisionAnswer = Field(default_factory=DecisionAnswer)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    evidence_citations: List[EvidenceCitation] = Field(default_factory=list)
    timestamp: str = ""


class ConversationSession(BaseModel):
    session_id: str
    domain: str = "general"
    turns: List[ConversationTurn] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    long_term_memory_hash: str = ""  # MEMORY.md 内容的 MD5，用于多轮去重


class MemoryEntry(BaseModel):
    """记忆条目 — 短期/长期记忆的统一 API 传输模型"""
    id: str = ""
    content: str = ""
    memory_type: str = "short_term"       # "short_term" | "long_term"
    category: str = "fact"                # fact/decision/preference/entity/topic
    importance: float = 0.5
    session_id: str = ""
    domain: str = "general"
    created_at: str = ""
    expires_at: Optional[str] = None      # 短期记忆过期时间，长期记忆为 None


class DecisionRequest(BaseModel):
    question: str
    domain: Optional[str] = None
    connection_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None


class DecisionResponse(BaseModel):
    domain: str = ""
    intent: str = ""
    session_id: Optional[str] = None
    analyzed_query: Optional[AnalyzedQuery] = None
    evidence: List[EvidenceItem] = Field(default_factory=list)
    evidence_citations: List[EvidenceCitation] = Field(default_factory=list)
    answer: DecisionAnswer = Field(default_factory=DecisionAnswer)
    skill_trace: List[ToolTrace] = Field(default_factory=list)
    decision_mode: str = "rag_pipeline"  # "rag_pipeline" | "skill_reasoning"
    metadata: Dict[str, Any] = Field(default_factory=dict)