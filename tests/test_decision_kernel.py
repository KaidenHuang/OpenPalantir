"""
决策内核（decision_kernel.py）单元测试

测试 DecisionKernel 的请求路由和插件委托逻辑。
"""
from unittest.mock import MagicMock, patch

import pytest

from decision_engine.contracts import (
    DecisionAnswer,
    DecisionRequest,
    DecisionResponse,
)
from decision_engine.decision_kernel import DecisionKernel


class TestDecisionKernel:
    """DecisionKernel 单元测试"""

    def test_run_delegates_to_plugin(self):
        """验证内核将请求委托给领域插件"""
        kernel = DecisionKernel()

        mock_plugin = MagicMock()
        mock_plugin.run.return_value = {
            "domain": "workforce",
            "intent": "组织分析",
            "answer": DecisionAnswer(summary="测试回答"),
            "decision_mode": "rag_pipeline",
            "response_type": "normal",
            "evidence": [],
            "evidence_citations": [],
            "skill_trace": [],
        }

        with patch(
            "decision_engine.decision_kernel.plugin_registry.resolve",
            return_value=mock_plugin,
        ):
            request = DecisionRequest(question="测试问题", domain="workforce")
            response = kernel.run(request)

            assert isinstance(response, DecisionResponse)
            assert response.domain == "workforce"
            assert response.intent == "组织分析"
            mock_plugin.run.assert_called_once()

    def test_run_default_domain(self):
        """未指定 domain 时默认使用 workforce"""
        kernel = DecisionKernel()

        mock_plugin = MagicMock()
        mock_plugin.run.return_value = {
            "domain": "workforce",
            "intent": "",
            "answer": DecisionAnswer(),
            "decision_mode": "rag_pipeline",
            "response_type": "normal",
            "evidence": [],
            "evidence_citations": [],
            "skill_trace": [],
        }

        with patch(
            "decision_engine.decision_kernel.plugin_registry.resolve",
            return_value=mock_plugin,
        ) as mock_resolve:
            request = DecisionRequest(question="测试")
            kernel.run(request)

            mock_resolve.assert_called_once_with("workforce")

    def test_run_custom_domain(self):
        """指定 domain 时传递给插件"""
        kernel = DecisionKernel()

        mock_plugin = MagicMock()
        mock_plugin.run.return_value = {
            "domain": "finance",
            "intent": "",
            "answer": DecisionAnswer(),
            "decision_mode": "rag_pipeline",
            "response_type": "normal",
            "evidence": [],
            "evidence_citations": [],
            "skill_trace": [],
        }

        with patch(
            "decision_engine.decision_kernel.plugin_registry.resolve",
            return_value=mock_plugin,
        ) as mock_resolve:
            request = DecisionRequest(question="分析风险", domain="finance")
            kernel.run(request)

            mock_resolve.assert_called_once_with("finance")

    def test_run_passes_full_request(self):
        """验证完整请求传递给插件"""
        kernel = DecisionKernel()

        mock_plugin = MagicMock()
        mock_plugin.run.return_value = {
            "domain": "general",
            "intent": "",
            "answer": DecisionAnswer(),
            "decision_mode": "rag_pipeline",
            "response_type": "normal",
            "evidence": [],
            "evidence_citations": [],
            "skill_trace": [],
        }

        with patch(
            "decision_engine.decision_kernel.plugin_registry.resolve",
            return_value=mock_plugin,
        ):
            request = DecisionRequest(
                question="复杂问题",
                domain="general",
                session_id="session-abc",
                context={"key": "value"},
            )
            kernel.run(request)

            call_args = mock_plugin.run.call_args[0][0]
            assert call_args.question == "复杂问题"
            assert call_args.session_id == "session-abc"
            assert call_args.context["key"] == "value"

    def test_run_plugin_registry(self):
        """验证 plugin_registry 单例可用"""
        from decision_engine.plugin_registry import plugin_registry

        assert plugin_registry is not None, "plugin_registry 应为全局单例"
        # 默认至少应注册 workforce 插件
        plugin = plugin_registry.resolve("workforce")
        assert plugin is not None, "应能解析 workforce 插件"