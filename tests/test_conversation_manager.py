"""
ConversationManager 单元测试

测试会话管理的核心功能：创建/恢复/添加轮次/历史截断。
不依赖外部服务（Neo4j、LLM），文件 IO 用临时目录隔离（base_dir 构造参数）。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def _make_manager(tmpdir):
    """在临时目录中创建 _ConversationManager 实例"""
    from decision_engine.conversation_manager import _ConversationManager
    return _ConversationManager(base_dir=tmpdir)


class TestConversationManager:
    """会话管理器核心功能测试"""

    def test_all_io_stays_inside_base_dir(self):
        """隔离必须是全程的：以前只 patch 模块全局到构造结束，落盘仍写进 backend/data/conversations"""
        from decision_engine import conversation_manager as cm
        from decision_engine.contracts import AnalyzedQuery, DecisionAnswer
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = cm._ConversationManager(base_dir=tmpdir)
            sid = mgr.get_or_create(domain="general")
            mgr.add_turn(sid, "问题", AnalyzedQuery(), DecisionAnswer(summary="回答"))
            assert os.listdir(tmpdir) == [f"{sid}.json"]
            assert not os.path.exists(os.path.join(cm.CONVERSATIONS_DIR, f"{sid}.json"))

    def test_get_or_create_new(self):
        """无 session_id → 创建新会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = _make_manager(tmpdir)
            sid = mgr.get_or_create(domain="general")
            assert sid.startswith("sess_")
            session = mgr.get_session(sid)
            assert session is not None
            assert session.domain == "general"

    def test_get_or_create_existing(self):
        """已有 session_id → 恢复"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = _make_manager(tmpdir)
            sid = mgr.get_or_create(domain="workforce")
            sid2 = mgr.get_or_create(session_id=sid, domain="workforce")
            assert sid == sid2

    def test_add_turn(self):
        """添加对话轮次"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = _make_manager(tmpdir)
            sid = mgr.get_or_create(domain="general")
            from decision_engine.contracts import AnalyzedQuery, DecisionAnswer
            turn_id = mgr.add_turn(
                sid, "测试问题",
                AnalyzedQuery(domain="general"),
                DecisionAnswer(summary="测试回答"),
            )
            assert turn_id == "turn_1"
            session = mgr.get_session(sid)
            assert len(session.turns) == 1
            assert session.turns[0].question == "测试问题"

    def test_get_history_max_turns(self):
        """历史截断到 max_turns"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = _make_manager(tmpdir)
            sid = mgr.get_or_create()
            from decision_engine.contracts import AnalyzedQuery, DecisionAnswer
            for i in range(5):
                mgr.add_turn(
                    sid, f"问题{i}",
                    AnalyzedQuery(),
                    DecisionAnswer(summary=f"回答{i}"),
                )
            history = mgr.get_history(sid, max_turns=2)
            assert len(history) == 2
            assert history[0]["question"] == "问题3"
            assert history[1]["question"] == "问题4"

    def test_get_session_not_found(self):
        """不存在的 session → None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = _make_manager(tmpdir)
            assert mgr.get_session("nonexistent") is None

    def test_get_history_empty(self):
        """无 session → 空历史"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = _make_manager(tmpdir)
            history = mgr.get_history("nonexistent")
            assert history == []


if __name__ == "__main__":
    unittest.main()
