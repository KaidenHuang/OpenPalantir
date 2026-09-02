"""
证据融合（evidence_fusion.py）单元测试

测试去重、排序、citation 生成、源优先级等核心逻辑。
"""
import pytest

from decision_engine.contracts import AnalyzedQuery, RawEvidence
from decision_engine.evidence_fusion import EvidenceFusion, SOURCE_PRIORITY


class TestEvidenceFusion:
    """EvidenceFusion 单元测试"""

    def setup_method(self):
        self.fusion = EvidenceFusion()

    def test_fuse_basic(self, sample_query, sample_raw_evidence):
        """基本融合：去重+排序+citation"""
        query = AnalyzedQuery(**sample_query)
        result = self.fusion.fuse(sample_raw_evidence, query)

        assert len(result) >= 1, "应返回至少 1 条证据"
        # 按 relevance_score 降序排列
        for i in range(len(result) - 1):
            assert result[i].relevance_score >= result[i + 1].relevance_score, \
                "结果应按相关性降序排列"

    def test_fuse_deduplication(self):
        """去重：相同 content 的证据只保留一条"""
        query = AnalyzedQuery(domain="general", intent="测试")
        dup_evidence = [
            RawEvidence(
                source_type="entity",
                source_id="ent-001",
                content={"name": "张三", "type": "人员"},
                relevance_score=0.8,
                metadata={},
            ),
            RawEvidence(
                source_type="entity",
                source_id="ent-002",
                content={"name": "张三", "type": "人员"},  # 完全相同
                relevance_score=0.9,
                metadata={},
            ),
        ]

        result = self.fusion.fuse(dup_evidence, query)
        assert len(result) == 1, "重复内容应去重"

    def test_fuse_source_priority(self):
        """源优先级加权：database_summary > document_summary > entity > graph_relation"""
        query = AnalyzedQuery(domain="general", intent="测试")
        evidence = [
            RawEvidence(
                source_type="graph_relation",
                source_id="rel-001",
                content={"predicate": "关联"},
                relevance_score=0.8,
                metadata={},
            ),
            RawEvidence(
                source_type="database_summary",
                source_id="db-001",
                content={"summary": "数据库摘要"},
                relevance_score=0.8,
                metadata={},
            ),
        ]

        result = self.fusion.fuse(evidence, query)
        db_item = next(r for r in result if r.source_type == "database_summary")
        graph_item = next(r for r in result if r.source_type == "graph_relation")
        db_idx = result.index(db_item)
        graph_idx = result.index(graph_item)
        assert db_idx < graph_idx, "database_summary 应排在 graph_relation 前面"

    def test_fuse_entity_match_bonus(self):
        """实体匹配加分：证据包含查询实体时加 0.2"""
        query = AnalyzedQuery(
            domain="general",
            intent="测试",
            entities=["张三"],
        )
        evidence = [
            RawEvidence(
                source_type="entity",
                source_id="ent-001",
                content={"name": "张三", "type": "人员"},
                relevance_score=0.5,  # 0.5 + 0.2(实体匹配) = 0.7
                metadata={},
            ),
            RawEvidence(
                source_type="entity",
                source_id="ent-002",
                content={"name": "李四", "type": "人员"},
                relevance_score=0.6,  # 0.6 + 0(无匹配) = 0.6
                metadata={},
            ),
        ]

        result = self.fusion.fuse(evidence, query)
        zhang_san = next(r for r in result if "张三" in str(r.payload))
        assert zhang_san.relevance_score >= 0.7, f"张三应有实体匹配加分，实际 {zhang_san.relevance_score}"

    def test_fuse_empty_input(self):
        """空输入返回空列表"""
        query = AnalyzedQuery(domain="general", intent="测试")
        result = self.fusion.fuse([], query)
        assert result == []

    def test_fuse_citation_generation(self):
        """citation 生成正确"""
        query = AnalyzedQuery(domain="general", intent="测试")
        evidence = [
            RawEvidence(
                source_type="document_summary",
                source_id="doc-001",
                content={"summary": "文档内容"},
                relevance_score=0.8,
                metadata={"doc_name": "报告.pdf", "datasource": "DOC://local"},
            ),
            RawEvidence(
                source_type="database_summary",
                source_id="db-001",
                content={"summary": "数据库内容"},
                relevance_score=0.7,
                metadata={"datasource": "DBS://conn/test_db"},
            ),
            RawEvidence(
                source_type="entity",
                source_id="ent-001",
                content={"name": "张三"},
                relevance_score=0.6,
                metadata={"name": "张三"},
            ),
            RawEvidence(
                source_type="graph_relation",
                source_id="rel-001",
                content={"source": "张三", "target": "李四", "predicate": "同事"},
                relevance_score=0.5,
                metadata={"source": "张三", "target": "李四"},
            ),
        ]

        result = self.fusion.fuse(evidence, query)
        for item in result:
            assert item.citation, f"{item.source_type} 应有 citation"
            assert item.evidence_id, f"{item.source_type} 应有 evidence_id"

    def test_fuse_content_hash(self):
        """content hash 去重：不同顺序的相同 dict 应视为重复"""
        query = AnalyzedQuery(domain="general", intent="测试")
        evidence = [
            RawEvidence(
                source_type="entity",
                source_id="ent-001",
                content={"name": "张三", "type": "人员"},
                relevance_score=0.8,
                metadata={},
            ),
            RawEvidence(
                source_type="entity",
                source_id="ent-002",
                content={"type": "人员", "name": "张三"},  # 键顺序不同
                relevance_score=0.9,
                metadata={},
            ),
        ]

        result = self.fusion.fuse(evidence, query)
        assert len(result) == 1, "键顺序不同的相同内容应去重"

    def test_fuse_summary_fallback(self):
        """summary 回退：从 content 或 metadata 取 summary"""
        query = AnalyzedQuery(domain="general", intent="测试")
        # graph_relation 无 summary 时，用 source→target 拼接
        evidence = [
            RawEvidence(
                source_type="graph_relation",
                source_id="rel-001",
                content={"source": "张三", "target": "李四", "predicate": "同事"},
                relevance_score=0.8,
                metadata={"source": "张三", "target": "李四"},
            ),
        ]

        result = self.fusion.fuse(evidence, query)
        assert len(result) == 1
        assert "张三" in result[0].summary, "graph_relation 应使用 source→target 拼接摘要"

    def test_source_priority_order(self):
        """SOURCE_PRIORITY 常量：database_summary > document_summary > entity > graph_relation"""
        assert SOURCE_PRIORITY["database_summary"] > SOURCE_PRIORITY["document_summary"]
        assert SOURCE_PRIORITY["document_summary"] > SOURCE_PRIORITY["entity"]
        assert SOURCE_PRIORITY["entity"] > SOURCE_PRIORITY["graph_relation"]