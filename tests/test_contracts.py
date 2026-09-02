"""
决策引擎合约（contracts.py）单元测试

测试 Pydantic 数据模型的序列化/反序列化。
"""
import json
from datetime import datetime

import pytest

from decision_engine.contracts import (
    AnalyzedQuery,
    ConversationSession,
    ConversationTurn,
    DecisionAnswer,
    DecisionRequest,
    DecisionResponse,
    EvidenceCitation,
    EvidenceItem,
    MemoryEntry,
    RawEvidence,
    StructuredContext,
    ToolTrace,
    WorkOrder,
)


class TestAnalyzedQuery:
    """AnalyzedQuery 数据模型测试"""

    def test_default_values(self):
        """默认值正确"""
        q = AnalyzedQuery()
        assert q.domain == "general"
        assert q.intent == ""
        assert q.entities == []
        assert q.entity_types == {}
        assert q.sub_questions == []

    def test_full_construction(self):
        """完整构造"""
        q = AnalyzedQuery(
            domain="finance",
            intent="风险评估",
            entities=["客户A", "交易B"],
            entity_types={"客户A": "客户", "交易B": "交易"},
            sub_questions=["客户A的风险等级？"],
            reasoning="分析客户风险",
            direct_answer="",
        )
        assert q.domain == "finance"
        assert q.intent == "风险评估"
        assert len(q.entities) == 2
        assert q.entity_types["客户A"] == "客户"

    def test_direct_answer_for_simple_queries(self):
        """简单问题（问候）的 direct_answer 字段"""
        q = AnalyzedQuery(
            intent="greeting",
            direct_answer="你好！我是 AI 助手，有什么可以帮你的？",
        )
        assert q.direct_answer != ""
        assert q.intent == "greeting"

    def test_serialization(self):
        """序列化到 JSON 再反序列化"""
        q = AnalyzedQuery(
            domain="workforce",
            intent="组织分析",
            entities=["研发部"],
            constraints={"dept": "研发部"},
        )
        data = q.model_dump()
        restored = AnalyzedQuery(**data)
        assert restored.domain == q.domain
        assert restored.intent == q.intent
        assert restored.entities == q.entities


class TestDecisionAnswer:
    """DecisionAnswer 数据模型测试"""

    def test_default_values(self):
        """默认值正确"""
        answer = DecisionAnswer()
        assert answer.summary == ""
        assert answer.recommendation == ""
        assert answer.work_orders == []

    def test_from_dict(self):
        """从 LLM 返回的 dict 解析"""
        data = {
            "summary": "张三和李四是同事关系",
            "situation_analysis": "两人在同一部门工作",
            "key_issues": [{"issue": "沟通效率", "severity": "中"}],
            "options": [
                {"option": "定期会议", "pros": "提升沟通", "cons": "时间成本"}
            ],
            "recommendation": "建议建立周例会制度",
            "work_orders": [
                {
                    "title": "建立周例会",
                    "priority": "P1",
                    "owner_role": "部门经理",
                    "steps": ["确定时间", "邀请参会人"],
                }
            ],
        }
        answer = DecisionAnswer.from_dict(data)
        assert answer.summary == "张三和李四是同事关系"
        assert answer.recommendation == "建议建立周例会制度"
        assert len(answer.work_orders) == 1
        assert answer.work_orders[0].title == "建立周例会"
        assert answer.work_orders[0].priority == "P1"

    def test_from_dict_empty(self):
        """空 dict 不报错"""
        answer = DecisionAnswer.from_dict({})
        assert answer.summary == ""

    def test_from_dict_recommendation_as_dict(self):
        """recommendation 为 dict 时自动转为 JSON 字符串"""
        data = {"recommendation": {"action": "重组", "reason": "效率"}}
        answer = DecisionAnswer.from_dict(data)
        assert isinstance(answer.recommendation, str)
        assert "action" in answer.recommendation


class TestDecisionRequest:
    """DecisionRequest 数据模型测试"""

    def test_minimal_construction(self):
        """最小构造"""
        req = DecisionRequest(question="测试问题")
        assert req.question == "测试问题"
        assert req.domain is None
        assert req.session_id is None

    def test_full_construction(self):
        """完整构造"""
        req = DecisionRequest(
            question="分析张三的关系网",
            domain="general",
            context={"entity": "张三"},
            session_id="session-123",
        )
        assert req.domain == "general"
        assert req.context["entity"] == "张三"


class TestDecisionResponse:
    """DecisionResponse 数据模型测试"""

    def test_default_values(self):
        """默认值正确"""
        resp = DecisionResponse()
        assert resp.domain == ""
        assert resp.decision_mode == "rag_pipeline"
        assert resp.response_type == "normal"
        assert resp.evidence == []
        assert resp.evidence_citations == []


class TestEvidenceItem:
    """EvidenceItem 数据模型测试"""

    def test_construction(self):
        """构造证据项"""
        item = EvidenceItem(
            evidence_id="doc-0",
            source_type="document_summary",
            source_name="报告.md",
            summary="测试摘要",
            relevance_score=0.85,
            citation="[文档: 报告.md]",
        )
        assert item.evidence_id == "doc-0"
        assert item.relevance_score == 0.85
        assert item.citation == "[文档: 报告.md]"


class TestToolTrace:
    """ToolTrace 数据模型测试"""

    def test_construction(self):
        """构造工具调用记录"""
        trace = ToolTrace(
            step=1,
            skill_name="search_entities",
            params={"query": "张三"},
            result_summary="找到 3 个实体",
            success=True,
            execution_time_ms=150.0,
        )
        assert trace.step == 1
        assert trace.skill_name == "search_entities"
        assert trace.success is True


class TestMemoryEntry:
    """MemoryEntry 数据模型测试"""

    def test_construction(self):
        """构造记忆条目"""
        entry = MemoryEntry(
            content="用户关注研发部门",
            memory_type="short_term",
            category="topic",
            importance=0.8,
            domain="workforce",
        )
        assert entry.memory_type == "short_term"
        assert entry.category == "topic"
        assert entry.importance == 0.8


class TestConversationTurn:
    """ConversationTurn 数据模型测试"""

    def test_construction(self):
        """构造对话轮次"""
        turn = ConversationTurn(
            turn_id="turn-001",
            question="测试问题",
            timestamp=datetime.now().isoformat(),
            response_type="simple",
        )
        assert turn.turn_id == "turn-001"
        assert turn.response_type == "simple"


class TestConversationSession:
    """ConversationSession 数据模型测试"""

    def test_construction(self):
        """构造会话"""
        session = ConversationSession(
            session_id="session-001",
            domain="general",
            long_term_memory_hash="abc123",
        )
        assert session.session_id == "session-001"
        assert session.turns == []
        assert session.long_term_memory_hash == "abc123"