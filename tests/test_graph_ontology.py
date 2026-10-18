"""
本体 → 图谱写入回归测试

验证「谓词归一化先于 relationship_id、边类型来自受控词表、非法类型名无法注入 Cypher、
predicate 不可原地更新、索引按 LinkType 预建」——全部使用 Mock Neo4j，不依赖真实服务。
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

import pytest

from knowledge_graph.relationship_repository import RelationshipRepository
from models.ids import compute_relationship_id
from ontology.predicates import FALLBACK_PREDICATE, canonical_rel_id
from ontology.registry import ontology_registry


@pytest.fixture()
def neo4j():
    mock = patch("knowledge_graph.relationship_repository.neo4j_conn")
    conn = mock.start()
    conn.execute_query.return_value = []
    yield conn
    mock.stop()


@pytest.fixture()
def repo():
    return RelationshipRepository()


def calls(conn):
    return [(c.args[0], c.args[1] if len(c.args) > 1 else {})
            for c in conn.execute_query.call_args_list]


class TestTypedEdgeWrite:

    def test_alias_predicate_becomes_typed_edge(self, repo, neo4j):
        result = repo.add_relationship({
            "subject": "张三", "object": "研发平台", "predicate": "负责",
            "description": "主导", "confidence": 1.0,
        })

        query, params = calls(neo4j)[0]
        assert "`管理`" in query
        assert params["predicate"] == "管理"
        assert params["raw_predicate"] == "负责"
        assert params["relationship_id"] == compute_relationship_id("张三", "管理", "研发平台")
        assert result["predicate"] == "管理"
        assert "RELATED_TO" not in query

    def test_unknown_predicate_falls_back_without_injection(self, repo, neo4j):
        repo.add_relationship({
            "subject": "A", "object": "B", "predicate": "精通`量子`",
        })

        query, params = calls(neo4j)[0]
        assert f"`{FALLBACK_PREDICATE}`" in query
        assert "精通" not in query
        assert params["predicate"] == FALLBACK_PREDICATE
        assert params["raw_predicate"] == "精通`量子`"

    def test_foreign_key_maps_to_dependency(self, repo, neo4j):
        repo.add_relationship({"subject": "orders:1", "object": "users:42",
                               "predicate": "Foreign key"})
        _, params = calls(neo4j)[0]
        assert params["predicate"] == "依赖"

    def test_batch_groups_one_query_per_link_type(self, repo, neo4j):
        result = repo.add_relationships([
            {"subject": "a", "object": "b", "predicate": "负责",
             "subject_id": "ib", "object_id": "io"},
            {"subject": "a", "object": "c", "predicate": "主管",
             "subject_id": "ib", "object_id": "ic"},
            {"subject": "d", "object": "e", "predicate": "外键",
             "subject_id": "id", "object_id": "ie"},
            {"subject": "f", "object": "g", "predicate": "无法归类",
             "subject_id": "if", "object_id": "ig"},
        ])

        typed = [q for q, _ in calls(neo4j)]
        assert len(typed) == 3                        # 管理 / 依赖 / 其他
        assert result["count"] == 4
        assert result["fallback_count"] == 1
        for query, params in calls(neo4j):
            predicates = {r["predicate"] for r in params["relationships"]}
            assert len(predicates) == 1
            assert f"`{predicates.pop()}`" in query

    def test_batch_create_branch_is_typed(self, repo, neo4j):
        repo.add_relationships(
            [{"subject": "a", "object": "b", "predicate": "包含",
              "subject_id": "ia", "object_id": "ib"}], use_create=True)

        query, _ = calls(neo4j)[0]
        assert "CREATE (s)-[rel:`包含`" in query

    def test_no_relationships_no_query(self, repo, neo4j):
        assert repo.add_relationships([])["count"] == 0
        neo4j.execute_query.assert_not_called()


class TestImmutabilityAndDelete:

    def test_update_rejects_predicate_change(self, repo, neo4j):
        assert repo.update_relationship("rid", {"predicate": "关联"}) is False
        neo4j.execute_query.assert_not_called()

    def test_update_other_props_allowed(self, repo, neo4j):
        neo4j.execute_query.return_value = [{"id": "rid"}]
        assert repo.update_relationship("rid", {"confidence": 0.9}) is True

    def test_delete_matches_without_edge_type(self, repo, neo4j):
        neo4j.execute_query.return_value = [{"deleted": 1}]
        assert repo.delete_relationship("rid") is True
        query, _ = calls(neo4j)[0]
        assert "MATCH ()-[r {relationship_id: $id}]-()" in query

    def test_delete_missing_returns_false(self, repo, neo4j):
        neo4j.execute_query.return_value = [{"deleted": 0}]
        assert repo.delete_relationship("不存在") is False


class TestReadSideIsTypeAgnostic:
    """读侧不得再假设单一 RELATED_TO 类型"""

    def test_queries_use_generic_relationships(self, repo, neo4j):
        neo4j.execute_query.return_value = []
        repo.list_relationships(limit=10)
        repo.get_edge_count()
        repo.get_entity_relationships("some-id")

        for query, _ in calls(neo4j):
            assert "RELATED_TO" not in query
        assert any("[r]" in q for q, _ in calls(neo4j))


class TestIndexCreation:

    def test_one_relationship_index_per_link_type(self):
        with patch("knowledge_graph.graph_performance.neo4j_conn") as conn:
            conn.execute_query.return_value = []
            from knowledge_graph.graph_performance import GraphPerformanceOptimizer
            GraphPerformanceOptimizer().create_indexes()

            queries = " ".join(c.args[0] for c in conn.execute_query.call_args_list)
            for key in ontology_registry.all_link_keys():
                assert f"rel_rid_{key}" in queries
                assert f"`{key}`" in queries
            assert "RELATED_TO" not in queries


class TestEntityIdConsistency:

    @pytest.mark.parametrize("raw", ["负责", "Foreign key", "随机谓词"])
    def test_same_names_same_id(self, raw):
        first, key, _ = canonical_rel_id("X", raw, "Y")
        second, _, _ = canonical_rel_id("X", raw, "Y")
        assert first == second == compute_relationship_id("X", key, "Y")
