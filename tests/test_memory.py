"""
记忆系统单元测试

测试 MemoryManager: 短期记忆 CRUD + 检索 + 过期清理 + 长期记忆读写
"""

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

from decision_engine.memory.memory_manager import (
    MemoryManager, SHORT_TERM_TTL_DAYS, MAX_LONG_TERM_ITEMS, MAX_LONG_TERM_CHARS,
)

# 获取模块引用，用于替换路径常量
import sys as _sys
_mem_module = _sys.modules["decision_engine.memory.memory_manager"]


class TestMemoryManager:
    """MemoryManager 单元测试"""

    @classmethod
    def setup_class(cls):
        """使用临时目录隔离 MEMORY.md"""
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._memory_dir = os.path.join(cls._tmpdir.name, "conversations")
        os.makedirs(cls._memory_dir, exist_ok=True)
        cls._memory_file = os.path.join(cls._memory_dir, "MEMORY.md")

        # 创建独立的 MemoryManager，指向临时 MEMORY.md
        cls.mm = MemoryManager()
        # 替换 MEMORY.md 路径
        cls._orig_dir = _mem_module._MEMORY_DIR
        cls._orig_file = _mem_module._MEMORY_FILE
        _mem_module._MEMORY_DIR = cls._memory_dir
        _mem_module._MEMORY_FILE = cls._memory_file

    @classmethod
    def teardown_class(cls):
        _mem_module._MEMORY_DIR = cls._orig_dir
        _mem_module._MEMORY_FILE = cls._orig_file
        cls._tmpdir.cleanup()

    # ── 短期记忆 ────────────────────────────────────────

    def test_add_and_retrieve_short_term(self):
        """添加短期记忆后能通过关键词检索到"""
        # 添加测试数据
        mid = self.mm.add_short_term(
            content="用户关注研发部门的组织架构调整",
            category="topic",
            importance=0.8,
            session_id="test_session_1",
            domain="workforce",
        )
        assert mid is not None, "应返回记忆 ID"
        assert len(mid) == 12, f"ID 应为 12 位，实际 {len(mid)}"

        # 检索（使用内容中的关键词）
        results = self.mm.retrieve_short_term(
            query="研发部门",
            domain="workforce",
            limit=5,
        )
        assert len(results) >= 1, "应检索到至少 1 条记忆"
        found = any("组织架构" in r["content"] for r in results)
        assert found, "应包含组织架构相关记忆"

    def test_retrieve_filters_by_domain(self):
        """检索应该按 domain 过滤"""
        self.mm.add_short_term(
            content="workforce 域的测试记忆",
            category="fact",
            session_id="test_session_2",
            domain="workforce",
        )
        self.mm.add_short_term(
            content="finance 域的测试记忆",
            category="fact",
            session_id="test_session_2",
            domain="finance",
        )

        results = self.mm.retrieve_short_term(
            query="测试记忆", domain="workforce", limit=10
        )
        for r in results:
            assert r["domain"] == "workforce", f"应为 workforce 域，实际 {r['domain']}"

    def test_batch_add(self):
        """批量添加短期记忆"""
        entries = [
            {"content": "批量测试 1", "category": "fact", "session_id": "batch_1", "domain": "workforce"},
            {"content": "批量测试 2", "category": "decision", "session_id": "batch_1", "domain": "workforce"},
            {"content": "批量测试 3", "category": "entity", "session_id": "batch_1", "domain": "workforce"},
        ]
        count = self.mm.add_short_term_batch(entries)
        assert count == 3, f"应添加 3 条，实际 {count}"

    def test_clean_expired(self):
        """清理过期记忆"""
        # 手动插入一条已过期的记忆（通过直接操作 ORM 绕过 add_short_term 的 TTL 设置）
        from config.database import SessionLocal
        from models.memory import ShortTermMemory
        import uuid

        db = SessionLocal()
        try:
            expired = ShortTermMemory(
                id=uuid.uuid4().hex[:12],
                content="过期记忆",
                category="fact",
                importance=0.3,
                session_id="expired_test",
                domain="workforce",
                created_at=datetime.now() - timedelta(days=10),
                expires_at=datetime.now() - timedelta(days=3),
            )
            db.add(expired)
            db.commit()

            # 清理
            cleaned = self.mm.clean_expired()
            assert cleaned >= 1, f"应清理至少 1 条，实际 {cleaned}"
        finally:
            db.close()

    # ── 长期记忆 ────────────────────────────────────────

    def test_write_and_read_long_term(self):
        """写入长期记忆后能正确读取"""
        self.mm.write_long_term_memories(
            preferences=["偏好数据驱动的决策方式"],
            decisions=["薪资调整采用市场对标法"],
        )
        result = self.mm.read_long_term_memories()
        assert result is not None, "应返回记忆数据"
        assert "偏好数据驱动的决策方式" in result["preferences"], "应包含偏好"
        assert "薪资调整采用市场对标法" in result["decisions"], "应包含决策"

    def test_merge_long_term_dedup(self):
        """合并长期记忆时自动去重"""
        self.mm.write_long_term_memories(
            preferences=["关注研发部门"],
            decisions=["Q3 完成组织调整"],
        )
        self.mm.merge_long_term_memories(
            new_prefs=["关注研发部门"],  # 重复
            new_decisions=["启动新项目"],
        )
        result = self.mm.read_long_term_memories()
        # 偏好不应重复
        pref_count = sum(1 for p in result["preferences"] if "研发部门" in p)
        assert pref_count == 1, f"偏好应去重，实际出现 {pref_count} 次"

    def test_long_term_hash_changes(self):
        """写入新内容后 hash 应变化"""
        self.mm.write_long_term_memories(
            preferences=["测试偏好 A"], decisions=["测试决策 A"]
        )
        hash1 = self.mm.get_long_term_hash()
        assert hash1, "hash 不应为空"

        self.mm.write_long_term_memories(
            preferences=["测试偏好 B"], decisions=["测试决策 B"]
        )
        hash2 = self.mm.get_long_term_hash()
        assert hash1 != hash2, "内容变化后 hash 应不同"

    def test_memory_file_auto_create(self):
        """MEMORY.md 不存在时自动创建"""
        # 删除文件
        if os.path.isfile(self._memory_file):
            os.remove(self._memory_file)

        result = self.mm.read_long_term_memories()
        # 应该自动创建空模板文件（首次创建时返回 None，因为尚无数据）
        assert os.path.isfile(self._memory_file), "MEMORY.md 应自动创建"

    # ── 工具方法 ────────────────────────────────────────

    def test_extract_keywords(self):
        """中文关键词提取"""
        keywords = self.mm._extract_keywords("研发部门的组织架构和人才梯队")
        assert len(keywords) >= 1, "应提取至少 1 个关键词"
        # 单字 "和" 不应被提取
        assert "和" not in keywords, "单字不应为关键词"

    def test_relevance_score(self):
        """相关性评分"""
        score = self.mm._relevance_score("研发部门组织架构调整", ["研发", "组织", "调整"])
        assert score > 0.5, f"高相关性应有高分，实际 {score}"

        score = self.mm._relevance_score("研发部门组织架构调整", ["财务", "预算"])
        assert score == 0.0, f"无相关性应为 0，实际 {score}"

    def test_is_similar(self):
        """相似度判断"""
        assert self.mm._is_similar("偏好数据驱动的决策", "偏好数据驱动的决策方式")
        assert self.mm._is_similar("hello", "hello")  # 完全相同
        assert not self.mm._is_similar("偏好数据驱动", "财务预算管理")

    def test_parse_memory_md(self):
        """解析 MEMORY.md 格式"""
        content = """---
updated: 2026-09-01T14:30:00
domain: workforce
---

# 长期记忆

## 用户偏好
- 偏好 A
- 偏好 B

## 重要决策
- 决策 X
"""
        result = self.mm._parse_memory_md(content)
        assert len(result["preferences"]) == 2, f"应有 2 条偏好，实际 {len(result['preferences'])}"
        assert len(result["decisions"]) == 1, f"应有 1 条决策，实际 {len(result['decisions'])}"
        assert "偏好 A" in result["preferences"]
        assert "决策 X" in result["decisions"]


def run_tests():
    test = TestMemoryManager()
    passed = 0
    failed = 0

    test.setup_class()
    try:
        for name in dir(test):
            if name.startswith("test_"):
                method = getattr(test, name)
                try:
                    method()
                    print(f"  [OK] {name}")
                    passed += 1
                except Exception as e:
                    print(f"  [FAIL] {name}: {e}")
                    failed += 1
    finally:
        test.teardown_class()

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)