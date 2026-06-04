from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    metadata: Dict[str, Any] = Field(default_factory=dict)
