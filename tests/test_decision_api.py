"""
Decision API 路由单元测试

使用 FastAPI TestClient 测试 HTTP 端点，mock 所有外部依赖（LLM、Neo4j、MCP）。
不依赖后端运行或外部服务。
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from decision_engine.contracts import DecisionAnswer, DecisionResponse


def _create_test_app():
    """创建仅含 decision 路由的最小 FastAPI 应用"""
    from api.routes.decision import router
    app = FastAPI()
    app.include_router(router, prefix="/api/decision")
    return app


class TestDecisionAskAPI:
    """POST /api/decision/ask 测试"""

    @patch("api.routes.decision.decision_kernel")
    def test_ask_success(self, mock_kernel):
        """正常请求 → 200 + DecisionResponse"""
        mock_kernel.run.return_value = DecisionResponse(
            domain="workforce",
            intent="general",
            session_id="sess_test",
            answer=DecisionAnswer(
                summary="测试回答", confidence=0.8, confidence_reason="ok",
            ),
            decision_mode="agentic_rag",
            response_type="normal",
            confidence=0.8,
            needs_human_review=False,
            metadata={"total_turns": 1, "total_tool_calls": 0, "total_time_ms": 100},
        )
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.post("/api/decision/ask", json={
                "question": "技术部有多少人",
                "domain": "workforce",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"]["summary"] == "测试回答"
        assert data["confidence"] == 0.8
        assert data["session_id"] == "sess_test"

    @patch("api.routes.decision.decision_kernel")
    def test_ask_internal_error(self, mock_kernel):
        """内部异常 → 500 + detail 信息"""
        mock_kernel.run.side_effect = RuntimeError("LLM 调用失败")
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.post("/api/decision/ask", json={
                "question": "测试",
                "domain": "general",
            })
        assert resp.status_code == 500
        assert "LLM 调用失败" in resp.json()["detail"]

    @patch("api.routes.decision.decision_kernel")
    def test_ask_empty_question(self, mock_kernel):
        """空问题仍正常处理（由内核决定行为）"""
        mock_kernel.run.return_value = DecisionResponse(
            domain="general",
            answer=DecisionAnswer(summary="请输入问题", confidence=0.5),
            confidence=0.5,
        )
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.post("/api/decision/ask", json={"question": ""})
        assert resp.status_code == 200


class TestDecisionSessionAPI:
    """GET /api/decision/session/{session_id} 测试"""

    @patch("api.routes.decision._conv_manager")
    def test_get_session_found(self, mock_conv):
        """存在的会话 → 200"""
        mock_session = MagicMock()
        mock_session.model_dump.return_value = {
            "session_id": "sess_abc",
            "domain": "general",
            "turns": [],
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "long_term_memory_hash": "",
        }
        mock_conv.get_session.return_value = mock_session
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get("/api/decision/session/sess_abc")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess_abc"

    @patch("api.routes.decision._conv_manager")
    def test_get_session_not_found(self, mock_conv):
        """不存在的会话 → 404"""
        mock_conv.get_session.return_value = None
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.get("/api/decision/session/sess_nonexistent")
        assert resp.status_code == 404


if __name__ == "__main__":
    unittest.main()
