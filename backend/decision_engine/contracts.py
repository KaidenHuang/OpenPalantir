import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from system.logger import logger


class AnalyzedQuery(BaseModel):
    """检索关键词与领域标签 —— 决策引擎唯一还需要「分析结果」的消费点

    旧 9 字段宽假契约（intent/entities/entity_types/constraints/…）随
    query_analyzer 一起消亡：不再有生产它的模块，每个调用点都只能手工捏空壳。
    收窄为真实消费者使用的两个值。
    """
    domain: str = "general"
    keywords: List[str] = Field(default_factory=list)


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
    evidence_no: int = 0   # 证据编号（对应 resp.evidence[evidence_no-1], 1-based；0=未配到）
    citation: str
    source_type: str
    source_id: str
    datasource: str = ""   # DOC:// 或 DBS:// URI（可溯源时填充）
    node_id: str = ""      # 摘要树节点 ID（可溯源时填充）


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
    confidence: float = 0.0
    confidence_reason: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "DecisionAnswer":
        """从 LLM 返回的 dict 解析 DecisionAnswer"""
        work_orders = []
        for wo in data.get("work_orders") or []:
            if isinstance(wo, dict):
                work_orders.append(WorkOrder(**wo))
            else:
                logger.warning(f"[decision_answer] 跳过非 dict 类型的 work_order: {type(wo).__name__}")

        rec = data.get("recommendation")
        if isinstance(rec, dict):
            rec = json.dumps(rec, ensure_ascii=False)
        elif rec is None:
            rec = ""

        situation = data.get("situation_analysis")
        if isinstance(situation, dict):
            situation = json.dumps(situation, ensure_ascii=False)
        elif situation is None:
            situation = ""

        confidence = float(data.get("confidence") or 0.0)
        confidence = max(0.0, min(1.0, confidence))

        return cls(
            summary=str(data.get("summary") or situation or "")[:500],
            situation_analysis=situation,
            key_issues=data.get("key_issues") or [],
            options=data.get("options") or [],
            recommendation=rec,
            work_orders=work_orders,
            confidence=confidence,
            confidence_reason=str(data.get("confidence_reason") or ""),
        )


class ToolTrace(BaseModel):
    """单次工具调用的执行记录"""
    step: int = 0
    tool_name: str = ""
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
    tool_trace: List[ToolTrace] = Field(default_factory=list)
    timestamp: str = ""
    response_type: str = "normal"  # "normal" | "simple" | "no_data"


class ConversationSession(BaseModel):
    session_id: str
    domain: str = "general"
    turns: List[ConversationTurn] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    long_term_memory_hash: str = ""  # 长期记忆内容指纹 MD5，用于多轮去重注入


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
    scope: Optional[Dict[str, Any]] = None  # 提问作用域: {datasource, node_id, title}


class DecisionResponse(BaseModel):
    domain: str = ""
    intent: str = ""
    session_id: Optional[str] = None
    analyzed_query: Optional[AnalyzedQuery] = None
    evidence: List[EvidenceItem] = Field(default_factory=list)
    evidence_citations: List[EvidenceCitation] = Field(default_factory=list)
    answer: DecisionAnswer = Field(default_factory=DecisionAnswer)
    tool_trace: List[ToolTrace] = Field(default_factory=list)
    decision_mode: str = "agentic_rag"
    response_type: str = "normal"
    confidence: float = 0.0
    needs_human_review: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)