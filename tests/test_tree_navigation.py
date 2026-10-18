"""
摘要树导航与 scope 引用单元测试

测试 tools.py 的树瘦身/节点读取、decision_kernel 的引用提取、AgenticContext 的 scope 格式化。
"""

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

import pytest

from decision_engine.agentic.tools import (
    _compact_tree, _find_tree_nodes, _execute_read_summary_nodes, _execute_get_summary_detail,
)
from decision_engine.decision_kernel import _citation_targets


TEST_UUID = "pytest-wiki-nav"
LONG_TEXT = "很长的原文内容。" * 800  # 8000 字符，超过 4000 截断阈值

TREE = [
    {"title": "成员", "node_id": "001", "summary": "介绍成员", "text": "张三、李四。",
     "nodes": [
         {"title": "张三", "node_id": "001-1", "summary": "后端工程师",
          "text": LONG_TEXT, "nodes": []},
     ]},
    {"title": "职责", "node_id": "002", "summary": "职责划分", "text": "分工说明。", "nodes": []},
]


@pytest.fixture()
def nav_summary_file():
    summaries_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "backend", "data", "summaries", "DOC", TEST_UUID)
    os.makedirs(summaries_dir, exist_ok=True)
    path = os.path.join(summaries_dir, "doc.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"doc_name": "doc.md", "doc_description": "测试文档", "structure": TREE},
                  f, ensure_ascii=False)
    yield f"DOC://{TEST_UUID}/doc.md"
    shutil.rmtree(summaries_dir, ignore_errors=True)


class TestCompactTree:

    def test_strips_text_keeps_hierarchy(self):
        compact = _compact_tree(TREE)
        assert len(compact) == 2
        assert compact[0]["node_id"] == "001"
        assert "text" not in compact[0]
        assert compact[0]["nodes"][0]["node_id"] == "001-1"
        assert "text" not in compact[0]["nodes"][0]
        assert "nodes" not in compact[1]  # 无子节点不保留空列表

    def test_empty(self):
        assert _compact_tree([]) == []
        assert _compact_tree(None) == []


class TestFindTreeNodes:

    def test_finds_across_depth(self):
        found = []
        _find_tree_nodes(TREE, {"001-1", "002"}, found)
        assert {n["node_id"] for n in found} == {"001-1", "002"}

    def test_depth_guard(self):
        leaf = {"title": "", "node_id": "level-15", "summary": "", "text": "", "nodes": []}
        node = leaf
        for i in range(15):
            node = {"title": "", "node_id": f"l{i}", "summary": "", "text": "", "nodes": [node]}
        found = []
        _find_tree_nodes([node], {"level-15"}, found)
        assert found == []  # 第 15 层超出深度保护（12 层）


class TestReadSummaryNodes:

    def test_returns_node_text(self, nav_summary_file):
        result = _execute_read_summary_nodes(
            {"datasource": nav_summary_file, "node_ids": ["001", "002"]})
        assert "error" not in result
        nodes = {n["node_id"]: n for n in result["nodes"]}
        assert set(nodes) == {"001", "002"}
        assert nodes["001"]["text"] == "张三、李四。"

    def test_truncation_flag(self, nav_summary_file):
        result = _execute_read_summary_nodes(
            {"datasource": nav_summary_file, "node_ids": ["001-1"]})
        node = result["nodes"][0]
        assert len(node["text"]) <= 4000
        assert node.get("truncated") is True

    def test_missing_node_ids_reported(self, nav_summary_file):
        result = _execute_read_summary_nodes(
            {"datasource": nav_summary_file, "node_ids": ["001", "999"]})
        assert result["missing_node_ids"] == ["999"]

    def test_rejects_non_doc_datasource(self):
        result = _execute_read_summary_nodes(
            {"datasource": "DBS://abc/db", "node_ids": ["001"]})
        assert "error" in result

    def test_requires_params(self):
        assert "error" in _execute_read_summary_nodes({"datasource": "", "node_ids": []})

    def test_unknown_datasource(self):
        result = _execute_read_summary_nodes(
            {"datasource": "DOC://no-such-uuid/x.md", "node_ids": ["001"]})
        assert "error" in result


class TestGetSummaryDetailCompact:

    def test_doc_branch_returns_skeleton(self, nav_summary_file):
        result = _execute_get_summary_detail({"datasource": nav_summary_file})
        assert result["type"] == "document"
        assert "read_summary_nodes" in result["note"]
        assert "text" not in result["structure"][0]
        assert result["structure"][0]["nodes"][0]["node_id"] == "001-1"
        assert result["name"] == "doc.md"

    def test_bad_datasource(self):
        assert "error" in _execute_get_summary_detail({"datasource": ""})
        assert "error" in _execute_get_summary_detail({"datasource": "http://x"})


class TestCitationTargets:

    def test_nodes_capped_at_three(self):
        payload = {"datasource": "DOC://u/x.md",
                   "nodes": [{"node_id": str(i), "title": f"t{i}"} for i in range(5)]}
        targets = _citation_targets(payload)
        assert len(targets) == 3
        assert targets[0] == {"datasource": "DOC://u/x.md", "node_id": "0", "title": "t0"}

    def test_single_node_payload(self):
        payload = {"datasource": "DOC://u/x.md", "node_id": "7", "name": "章节"}
        assert _citation_targets(payload) == [
            {"datasource": "DOC://u/x.md", "node_id": "7", "title": "章节"}]

    def test_document_level_fallback(self):
        payload = {"datasource": "DOC://u/x.md", "name": "文档名"}
        assert _citation_targets(payload) == [
            {"datasource": "DOC://u/x.md", "node_id": "", "title": "文档名"}]

    def test_without_datasource(self):
        assert _citation_targets({"nodes": [{"node_id": "1"}]}) == []


class TestFormatScope:

    def _ctx(self, scope):
        from decision_engine.agentic.context import AgenticContext
        return AgenticContext(question="q", domain="general", scope=scope)

    def test_empty_scope(self):
        assert self._ctx({}).format_scope() == ""

    def test_page_scope(self):
        text = self._ctx({"datasource": "DOC://u/x.md", "title": "绩效页"}).format_scope()
        assert "绩效页" in text
        assert "DOC://u/x.md" in text
        assert "read_summary_nodes" in text

    def test_node_scope(self):
        text = self._ctx({"datasource": "DOC://u/x.md", "node_id": "001"}).format_scope()
        assert "节点 `001`" in text
