"""
决策内核（decision_kernel.py）单元测试

测试 Agentic RAG 架构下的 DecisionKernel。
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# 确保 backend 在 sys.path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from decision_engine.agentic.engine import (
    AgenticEngine, quick_check_intent, SIMPLE_DEFAULTS,
)
from decision_engine.agentic.seed_retriever import SeedRetriever
from decision_engine.agentic.types import AgenticResult, Observation, SeedResult
from decision_engine.contracts import (
    AnalyzedQuery, DecisionAnswer, DecisionRequest, DecisionResponse,
)
from decision_engine.decision_kernel import DecisionKernel, inject_memories, load_domain_config


class TestQuickCheckIntent:
    """快速意图检测测试"""

    def test_greeting(self):
        assert quick_check_intent("你好") == "greeting"
        assert quick_check_intent("您好啊") == "greeting"
        assert quick_check_intent("hello") == "greeting"
        assert quick_check_intent("早上好") == "greeting"

    def test_identity(self):
        assert quick_check_intent("你是谁") == "identity"
        assert quick_check_intent("你叫什么名字") == "identity"

    def test_capability(self):
        assert quick_check_intent("你能做什么") == "capability"
        assert quick_check_intent("你有什么功能") == "capability"

    def test_farewell(self):
        assert quick_check_intent("再见") == "farewell"
        assert quick_check_intent("拜拜") == "farewell"

    def test_thanks(self):
        assert quick_check_intent("谢谢") == "thanks"
        assert quick_check_intent("感谢") == "thanks"

    def test_complex(self):
        assert quick_check_intent("分析技术部的人员流失情况") == "complex"
        assert quick_check_intent("张三在哪个部门工作") == "complex"
        assert quick_check_intent("查询2024年的财务报表") == "complex"


class TestTokenize:
    """SeedRetriever 分词测试"""

    def test_basic_tokenization(self):
        kw = SeedRetriever._tokenize("张三的能力，怎么样")
        assert "张三" in kw
        assert "能力" in kw

    def test_filter_stop_words(self):
        kw = SeedRetriever._tokenize("当前有哪几个部门")
        assert "部门" in kw
        assert "当前" not in kw
        assert "几个" not in kw

    def test_chinese_punctuation(self):
        kw = SeedRetriever._tokenize("技术部，人员流失？")
        assert "技术部" in kw
        assert "人员" in kw
        assert "流失" in kw

    def test_empty_question(self):
        kw = SeedRetriever._tokenize("")
        assert kw == []


class TestLoadDomainConfig:
    """领域配置加载测试"""

    def test_load_general(self):
        config = load_domain_config("general")
        assert "entity_types" in config
        assert "skill_domains" in config

    def test_load_workforce(self):
        config = load_domain_config("workforce")
        assert config.get("description") == "人力资源领域"

    def test_unknown_domain_fallback(self):
        """未知领域回退到 general"""
        config = load_domain_config("nonexistent")
        assert "entity_types" in config

    def test_caching(self):
        """配置缓存生效"""
        c1 = load_domain_config("general")
        c2 = load_domain_config("general")
        assert c1 is c2  # 同一对象引用


class TestAgenticEngineParseFinal:
    """AgenticEngine 最终答案解析测试"""

    @staticmethod
    def _make_engine():
        """创建 mock 的 AgenticEngine（不需要真实 LLM）"""
        mock_tools = MagicMock()
        mock_llm = MagicMock()
        engine = AgenticEngine.__new__(AgenticEngine)
        engine.tools = mock_tools
        engine.llm = mock_llm
        engine.seed_retriever = MagicMock()
        engine._prompt_template = ""
        return engine

    def test_parse_valid_json(self):
        engine = self._make_engine()
        response = {
            "content": json.dumps({
                "summary": "测试摘要",
                "situation_analysis": "分析内容",
                "confidence": 0.85,
                "confidence_reason": "证据充分",
                "key_issues": [{"issue": "问题1", "severity": "high"}],
                "options": [],
                "recommendation": "建议A",
                "work_orders": [],
            })
        }
        answer, conf, reason = engine._parse_final(response)
        assert answer.summary == "测试摘要"
        assert conf == 0.85
        assert reason == "证据充分"
        assert len(answer.key_issues) == 1

    def test_parse_json_in_code_block(self):
        engine = self._make_engine()
        response = {
            "content": '```json\n{"summary": "代码块中的JSON", "confidence": 0.7, "confidence_reason": "ok"}\n```'
        }
        answer, conf, reason = engine._parse_final(response)
        assert answer.summary == "代码块中的JSON"
        assert conf == 0.7

    def test_parse_invalid_json(self):
        engine = self._make_engine()
        response = {"content": "这是一段较长的非 JSON 格式回答文本，包含了关于技术部门人员配置的详细分析结果，但未能格式化为结构化 JSON 输出。" * 2}
        answer, conf, reason = engine._parse_final(response)
        assert "较长的非 JSON" in answer.summary
        assert conf == 0.4

    def test_parse_meta_commentary_rejected(self):
        """LLM 输出元评论（如'事实性查询，直接回答即可'）应被拒绝"""
        engine = self._make_engine()
        response = {"content": "该问题为对组织部门名单的事实性查询，直接回答即可。"}
        answer, conf, reason = engine._parse_final(response)
        assert conf == 0.2
        assert "未能获取" in answer.summary
        assert "元评论" in reason

    def test_parse_short_non_json_rejected(self):
        """过短的非 JSON 文本应被当作元评论拒绝"""
        engine = self._make_engine()
        response = {"content": "无需调用工具"}
        answer, conf, _ = engine._parse_final(response)
        assert conf == 0.2

    def test_parse_long_non_json_kept(self):
        """较长的非 JSON 文本（不含元评论模式）保留为 summary"""
        engine = self._make_engine()
        long_text = "根据检索结果，技术部目前有15名员工，分为前端组、后端组和测试组三个小组。" * 3
        response = {"content": long_text}
        answer, conf, _ = engine._parse_final(response)
        assert conf == 0.4
        assert "技术部" in answer.summary

    def test_parse_history_reference_penalized(self):
        """答案引用历史对话而非工具数据时，置信度被压低"""
        engine = self._make_engine()
        response = {
            "content": json.dumps({
                "summary": "根据历史对话记录，系统此前已确认当前共有9个部门。",
                "confidence": 0.8,
                "confidence_reason": "历史数据",
            })
        }
        answer, conf, reason = engine._parse_final(response)
        assert conf <= 0.3
        assert "历史" in reason

    def test_parse_history_meta_in_content_rejected(self):
        """非 JSON 内容含'此前已确认'时被视为元评论"""
        engine = self._make_engine()
        response = {"content": "根据历史对话，此前已确认有9个部门，完整名单已在上方列出。"}
        answer, conf, _ = engine._parse_final(response)
        assert conf == 0.2

    def test_parse_none_response(self):
        engine = self._make_engine()
        answer, conf, reason = engine._parse_final(None)
        assert "未能生成" in answer.summary
        assert conf == 0.3

    def test_parse_empty_content(self):
        engine = self._make_engine()
        answer, conf, reason = engine._parse_final({"content": ""})
        assert conf == 0.3

    def test_confidence_clamped(self):
        engine = self._make_engine()
        response = {
            "content": json.dumps({
                "summary": "test", "confidence": 1.5, "confidence_reason": "溢出",
            })
        }
        _, conf, _ = engine._parse_final(response)
        assert conf == 1.0  # 上限 1.0

    def test_parse_work_orders(self):
        engine = self._make_engine()
        response = {
            "content": json.dumps({
                "summary": "test",
                "confidence": 0.8,
                "confidence_reason": "ok",
                "work_orders": [
                    {
                        "title": "修复问题",
                        "priority": "P0",
                        "owner_role": "运维",
                        "steps": ["第一步", "第二步"],
                        "acceptance_criteria": ["验收标准"],
                    }
                ],
            })
        }
        answer, _, _ = engine._parse_final(response)
        assert len(answer.work_orders) == 1
        assert answer.work_orders[0].title == "修复问题"
        assert answer.work_orders[0].priority == "P0"


class TestSeedResult:
    """SeedResult 测试"""

    def test_empty(self):
        seed = SeedResult()
        assert seed.is_empty
        assert seed.format_for_prompt() == ""

    def test_format_with_docs(self):
        from decision_engine.contracts import RawEvidence
        seed = SeedResult(
            doc_summaries=[
                RawEvidence(
                    source_type="document_summary",
                    source_id="报告.md",
                    content={"summary": "测试报告摘要"},
                    relevance_score=0.8,
                    metadata={"datasource": "DOC://uuid/report"},
                )
            ],
        )
        assert not seed.is_empty
        text = seed.format_for_prompt()
        assert "报告.md" in text
        assert "测试报告摘要" in text

    def test_format_with_entities(self):
        seed = SeedResult(
            related_entities=[
                {"name": "张三", "type": "person"},
                {"name": "技术部", "type": "organization"},
            ],
        )
        text = seed.format_for_prompt()
        assert "张三" in text
        assert "技术部" in text


class TestAgenticContext:
    """AgenticContext 测试"""

    def test_compress_triggers_at_threshold(self):
        from decision_engine.agentic.context import AgenticContext
        ctx = AgenticContext(question="测试", domain="general")

        # 添加 7 条观察（超过 MAX_OBSERVATIONS_IN_CONTEXT=6）
        for i in range(7):
            ctx.add_observation(Observation(
                tool_name=f"tool_{i}",
                params={},
                summary=f"结果 {i}",
                full_result={},
                tool_call_id=f"id_{i}",
                execution_time_ms=10,
                success=True,
            ))

        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "测试"},
            {"role": "assistant", "content": "thinking"},
            {"role": "tool", "tool_call_id": "id_0", "content": "result"},
            {"role": "assistant", "content": "thinking"},
            {"role": "tool", "tool_call_id": "id_1", "content": "result"},
            {"role": "assistant", "content": "thinking"},
            {"role": "tool", "tool_call_id": "id_2", "content": "result"},
        ]
        compressed = ctx.compress(messages)

        # 压缩后：最早的 3 条被移入 running_summary
        assert len(ctx.observations) == 4
        assert "tool_0" in ctx.running_summary
        assert "tool_1" in ctx.running_summary
        assert "tool_2" in ctx.running_summary

    def test_no_compress_below_threshold(self):
        from decision_engine.agentic.context import AgenticContext
        ctx = AgenticContext(question="测试", domain="general")

        for i in range(3):
            ctx.add_observation(Observation(
                tool_name=f"tool_{i}", params={}, summary=f"r{i}",
                full_result={}, tool_call_id="", execution_time_ms=10, success=True,
            ))

        messages = [{"role": "system"}, {"role": "user"}]
        result = ctx.compress(messages)
        assert result is messages  # 不触发压缩，返回原对象

    def test_format_history(self):
        from decision_engine.agentic.context import AgenticContext
        ctx = AgenticContext(
            question="测试", domain="general",
            history=[
                {"question": "Q1", "summary": "A1"},
                {"question": "Q2", "summary": "A2"},
            ],
        )
        text = ctx.format_history()
        assert "Q1" in text
        assert "A1" in text
        assert "Q2" in text

    def test_format_memories(self):
        from decision_engine.agentic.context import AgenticContext
        ctx = AgenticContext(
            question="测试", domain="general",
            memories=[{"content": "用户关注技术部"}],
            long_term_memories={"preferences": ["偏好表格展示"], "decisions": []},
        )
        text = ctx.format_memories()
        assert "技术部" in text
        assert "表格展示" in text

    def test_format_entity_types(self):
        from decision_engine.agentic.context import AgenticContext
        ctx = AgenticContext(
            question="测试", domain="workforce",
            entity_types=[
                {"name": "person", "description": "员工"},
                {"name": "organization", "description": "部门"},
            ],
        )
        text = ctx.format_entity_types()
        assert "person" in text
        assert "员工" in text


class TestToolRegistry:
    """ToolRegistry 测试"""

    def test_get_definitions_merges(self):
        from decision_engine.agentic.tools import ToolRegistry
        mock_skill = MagicMock()
        mock_skill.get_tool_definitions.return_value = [
            {"type": "function", "function": {"name": "search_entities"}},
        ]
        mock_mcp = MagicMock()
        mock_mcp.get_tool_definitions.return_value = [
            {"type": "function", "function": {"name": "server1__tool1"}},
        ]

        registry = ToolRegistry(mock_skill, mock_mcp)
        tools = registry.get_definitions("general")
        assert len(tools) == 2

    def test_execute_skill_tool(self):
        from decision_engine.agentic.tools import ToolRegistry
        from decision_engine.tool_manager.skill.skill_loader import SkillResult
        mock_skill = MagicMock()
        result = SkillResult(
            skill_name="search_entities", success=True,
            data={"entities": [{"name": "张三"}]},
        )
        mock_skill.execute.return_value = result
        # mock skill.get() 返回的对象有 summarize 方法
        mock_skill_obj = MagicMock()
        mock_skill_obj.summarize.side_effect = lambda r: r.summarize()
        mock_skill.get.return_value = mock_skill_obj

        registry = ToolRegistry(mock_skill, None)
        obs = registry.execute("search_entities", {"query": "张三"})
        assert obs.success
        assert "张三" in obs.summary

    def test_execute_mcp_tool(self):
        from decision_engine.agentic.tools import ToolRegistry
        mock_skill = MagicMock()
        mock_mcp = MagicMock()
        mock_mcp.is_mcp_tool.return_value = True
        mock_mcp.execute.return_value = {"success": True, "data": "结果"}

        registry = ToolRegistry(mock_skill, mock_mcp)
        obs = registry.execute("server1__tool1", {"arg": "val"})
        assert obs.success
        mock_mcp.execute.assert_called_once()

    def test_execute_failure(self):
        from decision_engine.agentic.tools import ToolRegistry
        mock_skill = MagicMock()
        mock_skill.execute.side_effect = Exception("工具故障")

        registry = ToolRegistry(mock_skill, None)
        obs = registry.execute("broken_tool", {})
        assert not obs.success
        assert "工具故障" in obs.summary


class TestSkillResultSummarize:
    """SkillResult.summarize() 测试"""

    def test_failure(self):
        from decision_engine.tool_manager.skill.skill_loader import SkillResult
        r = SkillResult(skill_name="test", success=False, error="连接超时")
        assert "执行失败" in r.summarize()
        assert "连接超时" in r.summarize()

    def test_empty_data(self):
        from decision_engine.tool_manager.skill.skill_loader import SkillResult
        r = SkillResult(skill_name="test", success=True, data=None)
        assert "无结果" in r.summarize()

    def test_entities_pattern(self):
        from decision_engine.tool_manager.skill.skill_loader import SkillResult
        r = SkillResult(skill_name="search", success=True,
                        data={"entities": [{"name": "张三"}, {"name": "李四"}]})
        s = r.summarize()
        assert "找到实体" in s
        assert "张三" in s
        assert "李四" in s

    def test_documents_pattern(self):
        from decision_engine.tool_manager.skill.skill_loader import SkillResult
        r = SkillResult(skill_name="search", success=True,
                        data={"documents": [{"source": "a"}, {"source": "b"}]})
        assert "2 个相关文档" in r.summarize()

    def test_relations_pattern(self):
        from decision_engine.tool_manager.skill.skill_loader import SkillResult
        r = SkillResult(skill_name="rels", success=True,
                        data={"total_relations": 5, "relations": [1, 2, 3]})
        assert "5 条关系" in r.summarize()

    def test_communities_pattern(self):
        from decision_engine.tool_manager.skill.skill_loader import SkillResult
        r = SkillResult(skill_name="community", success=True,
                        data={"total_communities": 3, "communities": [1, 2, 3]})
        assert "3 个社区" in r.summarize()

    def test_found_true(self):
        from decision_engine.tool_manager.skill.skill_loader import SkillResult
        r = SkillResult(skill_name="detail", success=True,
                        data={"found": True, "entity": {"name": "王五"}})
        assert "找到实体" in r.summarize()
        assert "王五" in r.summarize()

    def test_found_false(self):
        from decision_engine.tool_manager.skill.skill_loader import SkillResult
        r = SkillResult(skill_name="detail", success=True,
                        data={"found": False, "message": "未匹配"})
        assert "未找到" in r.summarize()

    def test_list_data(self):
        from decision_engine.tool_manager.skill.skill_loader import SkillResult
        r = SkillResult(skill_name="test", success=True, data=[1, 2, 3])
        assert "3 条记录" in r.summarize()

    def test_long_text_truncated(self):
        from decision_engine.tool_manager.skill.skill_loader import SkillResult
        r = SkillResult(skill_name="test", success=True, data="x" * 600)
        s = r.summarize()
        assert len(s) <= 500
        assert s.endswith("...")

    def test_tables_pattern(self):
        from decision_engine.tool_manager.skill.skill_loader import SkillResult
        r = SkillResult(skill_name="db", success=True,
                        data={"tables": [{"table": "users"}, {"table": "orders"}]})
        s = r.summarize()
        assert "2 个表" in s
        assert "users" in s


class TestBuildEvidence:
    """AgenticEngine.build_evidence() 测试"""

    def test_empty_observations(self):
        evidence = AgenticEngine.build_evidence([])
        assert evidence == []

    def test_successful_observations(self):
        obs = [
            Observation(
                tool_name="search_entities",
                params={"query": "张三"},
                summary="找到实体: 张三",
                full_result={"entities": [{"name": "张三"}]},
                tool_call_id="tc_1",
                execution_time_ms=100,
                success=True,
            ),
            Observation(
                tool_name="get_entity_detail",
                params={"name": "张三"},
                summary="找到实体: 张三（技术部）",
                full_result={"found": True, "entity": {"name": "张三", "dept": "技术部"}},
                tool_call_id="tc_2",
                execution_time_ms=80,
                success=True,
            ),
        ]
        evidence = AgenticEngine.build_evidence(obs)
        assert len(evidence) == 2
        assert evidence[0].source_type == "search_entities"
        assert evidence[0].source_name == "张三"
        assert "张三" in evidence[0].summary
        assert evidence[1].source_name == "张三"

    def test_skips_failed_observations(self):
        obs = [
            Observation(
                tool_name="broken_tool",
                params={},
                summary="工具执行失败: 连接超时",
                full_result={"error": "连接超时"},
                tool_call_id="tc_1",
                execution_time_ms=5000,
                success=False,
            ),
        ]
        evidence = AgenticEngine.build_evidence(obs)
        assert evidence == []

    def test_evidence_id_sequential(self):
        obs = [
            Observation(
                tool_name=f"tool_{i}", params={}, summary=f"结果 {i}",
                full_result={}, tool_call_id="", execution_time_ms=10, success=True,
            )
            for i in range(3)
        ]
        evidence = AgenticEngine.build_evidence(obs)
        assert evidence[0].evidence_id == "obs_1"
        assert evidence[1].evidence_id == "obs_2"
        assert evidence[2].evidence_id == "obs_3"

    def test_citation_format(self):
        obs = [
            Observation(
                tool_name="search_entities",
                params={"query": "技术部"},
                summary="找到实体: 技术部",
                full_result={},
                tool_call_id="tc_1",
                execution_time_ms=50,
                success=True,
            ),
        ]
        evidence = AgenticEngine.build_evidence(obs)
        assert evidence[0].citation.startswith("[search_entities]")
        assert "技术部" in evidence[0].citation


class TestEmptyToolsFastFail:
    """空工具列表快速失败测试"""

    def test_no_tools_returns_degraded(self):
        """当无可用工具时，直接返回降级响应而不调用 LLM"""
        mock_tools = MagicMock()
        mock_tools.get_definitions.return_value = []
        mock_llm = MagicMock()

        engine = AgenticEngine.__new__(AgenticEngine)
        engine.tools = mock_tools
        engine.llm = mock_llm
        engine.seed_retriever = MagicMock()
        engine.seed_retriever.retrieve.return_value = SeedResult()
        engine._prompt_template = ""

        result = engine.run("有哪些部门", "workforce")
        assert result.total_turns == 0
        assert result.total_tool_calls == 0
        assert result.confidence == 0.1
        assert "无可用工具" in result.answer.summary
        # LLM 不应被调用
        mock_llm.call_with_tools.assert_not_called()


class TestDecisionKernelInit:
    """DecisionKernel._ensure_initialized() 测试"""

    @patch("decision_engine.decision_kernel.AgenticEngine")
    @patch("decision_engine.decision_kernel.MCPManager")
    @patch("decision_engine.decision_kernel.load_mcp_server_configs")
    @patch("decision_engine.decision_kernel.skill_registry")
    def test_init_success(self, mock_sr, mock_load_mcp, mock_mcp_cls, mock_ae_cls):
        """Skill + MCP 全部成功"""
        mock_sr.load_all.return_value = 3
        mock_load_mcp.return_value = [{"server_name": "test", "url": "http://test"}]
        kernel = DecisionKernel()
        kernel._ensure_initialized()
        mock_sr.load_all.assert_called_once()
        mock_mcp_cls.return_value.connect_all.assert_called_once()
        assert kernel._agentic is not None

    @patch("decision_engine.decision_kernel.AgenticEngine")
    @patch("decision_engine.decision_kernel.MCPManager")
    @patch("decision_engine.decision_kernel.load_mcp_server_configs")
    @patch("decision_engine.decision_kernel.skill_registry")
    def test_init_mcp_failure_degrades(self, mock_sr, mock_load_mcp, mock_mcp_cls, mock_ae_cls):
        """MCP 连接异常 → 降级为 Skill-only"""
        mock_sr.load_all.return_value = 3
        mock_load_mcp.return_value = [{"server_name": "test"}]
        mock_mcp_cls.return_value.connect_all.side_effect = Exception("连接被拒绝")
        kernel = DecisionKernel()
        kernel._ensure_initialized()
        assert kernel._agentic is not None

    @patch("decision_engine.decision_kernel.AgenticEngine")
    @patch("decision_engine.decision_kernel.MCPManager")
    @patch("decision_engine.decision_kernel.load_mcp_server_configs")
    @patch("decision_engine.decision_kernel.skill_registry")
    def test_init_no_mcp_config(self, mock_sr, mock_load_mcp, mock_mcp_cls, mock_ae_cls):
        """无 MCP 配置 → 正常降级"""
        mock_sr.load_all.return_value = 3
        mock_load_mcp.return_value = []
        kernel = DecisionKernel()
        kernel._ensure_initialized()
        mock_mcp_cls.assert_not_called()
        assert kernel._agentic is not None

    @patch("decision_engine.decision_kernel.AgenticEngine")
    @patch("decision_engine.decision_kernel.skill_registry")
    def test_idempotent_init(self, mock_sr, mock_ae_cls):
        """重复调用不重复初始化"""
        mock_sr.load_all.return_value = 3
        kernel = DecisionKernel()
        kernel._ensure_initialized()
        kernel._ensure_initialized()
        assert mock_sr.load_all.call_count == 1

    @patch("decision_engine.decision_kernel.AgenticEngine")
    @patch("decision_engine.decision_kernel.skill_registry")
    def test_init_creates_agentic_engine(self, mock_sr, mock_ae_cls):
        """初始化后 _agentic 不为 None"""
        mock_sr.load_all.return_value = 3
        kernel = DecisionKernel()
        assert kernel._agentic is None
        kernel._ensure_initialized()
        mock_ae_cls.assert_called_once()
        assert kernel._agentic is not None


class TestDecisionKernelRun:
    """DecisionKernel.run() 集成测试（mock 外部依赖）"""

    def _make_kernel(self):
        kernel = DecisionKernel()
        kernel._initialized = True
        kernel._agentic = MagicMock()
        return kernel

    @patch("decision_engine.decision_kernel.memory_extractor")
    @patch("decision_engine.decision_kernel.inject_memories")
    @patch("decision_engine.decision_kernel.conv_manager")
    def test_run_simple_intent(self, mock_conv, mock_inject, mock_extractor):
        """'你好' → simple 响应, confidence=1.0"""
        mock_conv.get_or_create.return_value = "sess_test"
        mock_conv.get_history.return_value = []
        kernel = self._make_kernel()
        req = DecisionRequest(question="你好")
        resp = kernel.run(req)
        assert resp.response_type == "simple"
        assert resp.confidence == 1.0
        kernel._agentic.run.assert_not_called()

    @patch("decision_engine.decision_kernel.memory_extractor")
    @patch("decision_engine.decision_kernel.inject_memories")
    @patch("decision_engine.decision_kernel.conv_manager")
    def test_run_complex_intent(self, mock_conv, mock_inject, mock_extractor):
        """复杂问题 → 调用 AgenticEngine.run()"""
        mock_conv.get_or_create.return_value = "sess_test"
        mock_conv.get_history.return_value = []
        kernel = self._make_kernel()
        kernel._agentic.run.return_value = AgenticResult(
            answer=DecisionAnswer(summary="测试回答", confidence=0.8, confidence_reason="ok"),
            confidence=0.8, confidence_reason="ok",
            observations=[], total_turns=1, total_tool_calls=0,
            total_time_ms=100, needs_human_review=False, running_summary="",
        )
        req = DecisionRequest(question="分析技术部人员结构")
        resp = kernel.run(req)
        assert resp.response_type == "normal"
        kernel._agentic.run.assert_called_once()

    @patch("decision_engine.decision_kernel.memory_extractor")
    @patch("decision_engine.decision_kernel.inject_memories")
    @patch("decision_engine.decision_kernel.conv_manager")
    def test_run_with_session_id(self, mock_conv, mock_inject, mock_extractor):
        """带 session_id → 响应保留同一 session_id"""
        mock_conv.get_or_create.return_value = "sess_abc"
        mock_conv.get_history.return_value = []
        kernel = self._make_kernel()
        kernel._agentic.run.return_value = AgenticResult(
            answer=DecisionAnswer(summary="回答", confidence=0.7, confidence_reason="ok"),
            confidence=0.7, confidence_reason="ok",
            observations=[], total_turns=1, total_tool_calls=0,
            total_time_ms=50, needs_human_review=False, running_summary="",
        )
        req = DecisionRequest(question="继续分析", session_id="sess_abc")
        resp = kernel.run(req)
        assert resp.session_id == "sess_abc"

    @patch("decision_engine.decision_kernel.memory_extractor")
    @patch("decision_engine.decision_kernel.inject_memories")
    @patch("decision_engine.decision_kernel.conv_manager")
    def test_run_evidence_citations_from_key_issues(self, mock_conv, mock_inject, mock_ext):
        """LLM 答案含 evidence 引用 → 正确匹配"""
        mock_conv.get_or_create.return_value = "sess_t"
        mock_conv.get_history.return_value = []
        kernel = self._make_kernel()
        obs = [Observation(
            tool_name="search_entities", params={"query": "技术部"},
            summary="找到实体: 技术部", full_result={"entities": []},
            tool_call_id="tc_1", execution_time_ms=100, success=True,
        )]
        kernel._agentic.run.return_value = AgenticResult(
            answer=DecisionAnswer.from_dict({
                "summary": "技术部有15人",
                "confidence": 0.8, "confidence_reason": "ok",
                "key_issues": [{"issue": "人员", "evidence": ["找到实体: 技术部"]}],
            }),
            confidence=0.8, confidence_reason="ok",
            observations=obs, total_turns=1, total_tool_calls=1,
            total_time_ms=200, needs_human_review=False, running_summary="",
        )
        resp = kernel.run(DecisionRequest(question="技术部有多少人"))
        assert len(resp.evidence_citations) == 1
        assert resp.evidence_citations[0].citation == "找到实体: 技术部"

    @patch("decision_engine.decision_kernel.memory_extractor")
    @patch("decision_engine.decision_kernel.inject_memories")
    @patch("decision_engine.decision_kernel.conv_manager")
    def test_run_evidence_citations_fallback(self, mock_conv, mock_inject, mock_ext):
        """key_issues 为空时从 observations 生成 citations"""
        mock_conv.get_or_create.return_value = "sess_t"
        mock_conv.get_history.return_value = []
        kernel = self._make_kernel()
        obs = [Observation(
            tool_name="search_entities", params={"query": "部门"},
            summary="找到 9 个部门", full_result={},
            tool_call_id="tc_1", execution_time_ms=50, success=True,
        )]
        kernel._agentic.run.return_value = AgenticResult(
            answer=DecisionAnswer(summary="有9个部门", confidence=0.9, confidence_reason="ok"),
            confidence=0.9, confidence_reason="ok",
            observations=obs, total_turns=1, total_tool_calls=1,
            total_time_ms=100, needs_human_review=False, running_summary="",
        )
        resp = kernel.run(DecisionRequest(question="有哪些部门"))
        assert len(resp.evidence_citations) == 1
        assert resp.evidence_citations[0].source_type == "search_entities"

    @patch("decision_engine.decision_kernel.memory_extractor")
    @patch("decision_engine.decision_kernel.inject_memories")
    @patch("decision_engine.decision_kernel.conv_manager")
    def test_run_metadata_populated(self, mock_conv, mock_inject, mock_ext):
        """metadata 含 total_turns/total_tool_calls/total_time_ms"""
        mock_conv.get_or_create.return_value = "sess_t"
        mock_conv.get_history.return_value = []
        kernel = self._make_kernel()
        kernel._agentic.run.return_value = AgenticResult(
            answer=DecisionAnswer(summary="ok", confidence=0.8, confidence_reason="ok"),
            confidence=0.8, confidence_reason="ok",
            observations=[], total_turns=3, total_tool_calls=2,
            total_time_ms=1500, needs_human_review=False, running_summary="摘要",
        )
        resp = kernel.run(DecisionRequest(question="分析"))
        assert resp.metadata["total_turns"] == 3
        assert resp.metadata["total_tool_calls"] == 2
        assert resp.metadata["total_time_ms"] == 1500


class TestInjectMemories:
    """inject_memories() 测试"""

    @patch("decision_engine.decision_kernel.conv_manager")
    @patch("decision_engine.decision_kernel.memory_manager")
    def test_inject_short_term_memories(self, mock_mm, mock_conv):
        """短期记忆注入到 request.context"""
        mock_mm.retrieve_short_term.return_value = [{"content": "关注研发"}]
        mock_mm.read_long_term_memories.return_value = {}
        req = DecisionRequest(question="测试", session_id="sess_1")
        inject_memories(req, "general")
        assert "short_term_memories" in req.context
        assert len(req.context["short_term_memories"]) == 1

    @patch("decision_engine.decision_kernel.conv_manager")
    @patch("decision_engine.decision_kernel.memory_manager")
    def test_inject_failure_graceful(self, mock_mm, mock_conv):
        """记忆检索异常不中断"""
        mock_mm.retrieve_short_term.side_effect = Exception("DB连接失败")
        req = DecisionRequest(question="测试")
        inject_memories(req, "general")
        assert "short_term_memories" not in req.context

    @patch("decision_engine.decision_kernel.conv_manager")
    @patch("decision_engine.decision_kernel.memory_manager")
    def test_inject_no_session(self, mock_mm, mock_conv):
        """无 session 时不注入长期记忆"""
        mock_mm.retrieve_short_term.return_value = []
        mock_mm.read_long_term_memories.return_value = {
            "preferences": ["偏好表格"], "decisions": [],
        }
        mock_conv.get_session.return_value = None
        req = DecisionRequest(question="测试")
        inject_memories(req, "general")
        assert "long_term_memories" not in req.context


class TestAgenticEngineRun:
    """AgenticEngine.run() ReAct 循环测试"""

    @staticmethod
    def _make_engine(mock_llm=None, mock_tools=None):
        engine = AgenticEngine.__new__(AgenticEngine)
        engine.tools = mock_tools or MagicMock()
        engine.llm = mock_llm or MagicMock()
        engine.seed_retriever = MagicMock()
        engine.seed_retriever.retrieve.return_value = SeedResult()
        engine._prompt_template = ""
        return engine

    def test_single_turn_answer(self):
        """LLM 首轮无 tool_calls → 直接返回答案"""
        mock_llm = MagicMock()
        mock_tools = MagicMock()
        mock_tools.get_definitions.return_value = [
            {"type": "function", "function": {"name": "test_tool"}},
        ]
        mock_llm.call_with_tools.return_value = {
            "content": json.dumps({
                "summary": "测试回答", "confidence": 0.8, "confidence_reason": "ok",
            }),
            "tool_calls": [],
        }
        engine = self._make_engine(mock_llm, mock_tools)
        result = engine.run("测试问题", "general")
        assert result.total_turns == 1
        assert result.total_tool_calls == 0
        assert result.answer.summary == "测试回答"

    def test_multi_turn_tool_calls(self):
        """LLM 调用工具 → 执行 → 第二轮给出答案"""
        mock_llm = MagicMock()
        mock_tools = MagicMock()
        mock_tools.get_definitions.return_value = [
            {"type": "function", "function": {"name": "search"}},
        ]
        mock_tools.execute.return_value = Observation(
            tool_name="search", params={"query": "test"},
            summary="搜索结果", full_result={"data": "ok"},
            tool_call_id="tc_1", execution_time_ms=50, success=True,
        )
        mock_llm.call_with_tools.side_effect = [
            {
                "content": "thinking",
                "tool_calls": [{
                    "id": "tc_1",
                    "function": {"name": "search", "arguments": '{"query": "test"}'},
                }],
            },
            {
                "content": json.dumps({
                    "summary": "最终回答", "confidence": 0.9, "confidence_reason": "工具数据",
                }),
                "tool_calls": [],
            },
        ]
        engine = self._make_engine(mock_llm, mock_tools)
        result = engine.run("搜索测试", "general")
        assert result.total_turns == 2
        assert result.total_tool_calls == 1
        assert result.answer.summary == "最终回答"

    def test_max_turns_force_synthesis(self):
        """MAX_TURNS 耗尽 → 强制综合，confidence ≤ 0.5"""
        old_max = AgenticEngine.MAX_TURNS
        AgenticEngine.MAX_TURNS = 2
        try:
            mock_llm = MagicMock()
            mock_tools = MagicMock()
            mock_tools.get_definitions.return_value = [
                {"type": "function", "function": {"name": "search"}},
            ]
            mock_tools.execute.return_value = Observation(
                tool_name="search", params={},
                summary="结果", full_result={},
                tool_call_id="tc_1", execution_time_ms=10, success=True,
            )
            mock_llm.call_with_tools.side_effect = [
                {
                    "content": "",
                    "tool_calls": [{
                        "id": "tc_1",
                        "function": {"name": "search", "arguments": "{}"},
                    }],
                },
                {
                    "content": "",
                    "tool_calls": [{
                        "id": "tc_2",
                        "function": {"name": "search", "arguments": "{}"},
                    }],
                },
                {
                    "content": json.dumps({
                        "summary": "强制综合回答", "confidence": 0.5, "confidence_reason": "ok",
                    }),
                    "tool_calls": [],
                },
            ]
            engine = self._make_engine(mock_llm, mock_tools)
            result = engine.run("复杂问题", "general")
            assert result.total_turns == 2
            assert result.total_tool_calls == 2
            assert result.confidence <= 0.5
        finally:
            AgenticEngine.MAX_TURNS = old_max

    def test_llm_returns_none(self):
        """LLM 返回 None → 提前退出循环，落入强制综合"""
        mock_llm = MagicMock()
        mock_tools = MagicMock()
        mock_tools.get_definitions.return_value = [
            {"type": "function", "function": {"name": "test"}},
        ]
        mock_llm.call_with_tools.return_value = None
        engine = self._make_engine(mock_llm, mock_tools)
        result = engine.run("测试", "general")
        assert result.total_tool_calls == 0
        assert result.confidence <= 0.3
        assert "未能生成" in result.answer.summary

    def test_execute_tool_call_bad_json(self):
        """tool_call arguments 为无效 JSON → params={}"""
        engine = self._make_engine()
        tc = {
            "id": "tc_1",
            "function": {"name": "test_tool", "arguments": "invalid json{"},
        }
        obs = engine._execute_tool_call(tc)
        assert obs.tool_call_id == "tc_1"
        engine.tools.execute.assert_called_once_with("test_tool", {})


if __name__ == "__main__":
    unittest.main()
