"""
DecisionKernel — 决策内核

职责：路由到 AgenticEngine，管理会话和记忆。
不再使用插件层和固定管道。
"""
import hashlib
import os
from functools import lru_cache
from typing import Optional

import yaml

from decision_engine.agentic.engine import AgenticEngine, quick_check_intent, SIMPLE_DEFAULTS
from decision_engine.agentic.multi_agent import MultiAgentEngine
from decision_engine.agentic.tools import ToolRegistry
from decision_engine.contracts import (
    AnalyzedQuery, DecisionAnswer, DecisionRequest, DecisionResponse,
    EvidenceCitation, ToolTrace,
)
from decision_engine.conversation_manager import conv_manager
from decision_engine.memory.memory_extractor import memory_extractor
from decision_engine.memory.memory_manager import memory_manager
from decision_engine.tool_manager.mcp.mcp_manager import MCPManager
from decision_engine.tool_manager.mcp.config import load_mcp_server_configs
from decision_engine.tool_manager.skill.skill_registry import skill_registry
from system.logger import logger


@lru_cache(maxsize=32)
def load_domain_config(domain: str) -> dict:
    """从 domain_config.yaml 加载领域配置（线程安全缓存）"""
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "domain_config.yaml",
    )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        domains = config.get("domains", {})
        return domains.get(domain, domains.get("general", {}))
    except Exception as e:
        logger.error(f"[kernel] 加载领域配置失败: {e}")
        return {}


def inject_memories(request: DecisionRequest, domain: str) -> None:
    """检索短期/长期记忆并注入到请求上下文"""
    try:
        session_id = request.session_id or ""

        short_term = memory_manager.retrieve_short_term(
            query=request.question, domain=domain, limit=5,
        )
        if short_term:
            request.context["short_term_memories"] = short_term
            logger.info(f"[kernel] 短期记忆注入: {len(short_term)}条")

        long_term = memory_manager.read_long_term_memories()
        if long_term and (long_term.get("preferences") or long_term.get("decisions")):
            current_hash = hashlib.md5(
                str(long_term).encode()
            ).hexdigest()
            session = conv_manager.get_session(session_id)
            if session and current_hash != session.long_term_memory_hash:
                request.context["long_term_memories"] = long_term
                session.long_term_memory_hash = current_hash
                conv_manager.save_session(session)
                logger.info("[kernel] 长期记忆注入")
    except Exception as e:
        logger.warning(f"[kernel] 记忆注入失败（降级运行）: {e}")


class DecisionKernel:
    """决策内核 — 全局会话管理 + AgenticEngine（惰性初始化）"""

    def __init__(self):
        self._agentic: Optional[MultiAgentEngine] = None
        self._initialized = False

    def _ensure_initialized(self):
        """惰性初始化：首次 run() 时加载 Skill、连接 MCP 并创建引擎"""
        if self._initialized:
            return
        self._initialized = True

        # 1. 加载内置 Skill 工具
        skills_root = os.path.join(os.path.dirname(__file__), "skills")
        count = skill_registry.load_all(skills_root, domains=["general"])
        logger.info(f"[kernel] Skill 工具加载完成: {count} 个")

        # 2. MCP 连接（加载配置 → 创建管理器 → 连接）
        mcp_manager = None
        try:
            mcp_configs = load_mcp_server_configs()
            if mcp_configs:
                mcp_manager = MCPManager(server_configs=mcp_configs)
                mcp_manager.connect_all()
                logger.info(f"[kernel] MCP 连接完成: {len(mcp_configs)} 个服务器")
        except Exception as e:
            logger.warning(f"[kernel] MCP 连接失败（降级为仅 Skill 模式）: {e}")
            mcp_manager = None

        tool_registry = ToolRegistry(skill_registry, mcp_manager)
        self._agentic = MultiAgentEngine(tool_registry)

    def run(self, request: DecisionRequest) -> DecisionResponse:
        """主入口"""
        self._ensure_initialized()

        # 1. 读取领域配置
        domain = request.domain or "general"
        domain_config = load_domain_config(domain)

        logger.info(
            f"[kernel] run domain={domain}, session_id={request.session_id}, "
            f"question={request.question[:60]}"
        )

        # 2. 会话管理
        session_id = conv_manager.get_or_create(request.session_id, domain=domain)

        # 3. 记忆注入
        inject_memories(request, domain)
        history = conv_manager.get_history(session_id)

        # 4. 快速判断：简单社交意图
        intent = quick_check_intent(request.question)
        if intent != "complex":
            return self._simple_response(intent, domain, session_id, request.question)

        # 5. Agentic 循环（唯一路径）
        result = self._agentic.run(
            question=request.question,
            domain=domain,
            entity_types=domain_config.get("entity_types", []),
            history=history,
            memories=request.context.get("short_term_memories", []),
            long_term_memories=request.context.get("long_term_memories", {}),
        )

        # 6. 提取记忆
        analyzed = AnalyzedQuery(
            domain=domain, intent="general",
            entities=[], entity_types={},
        )
        memory_extractor.extract_async(
            request.question, result.answer.summary, session_id, domain,
        )

        # 7. 构建工具追踪
        tool_trace = [
            ToolTrace(
                step=i + 1,
                tool_name=obs.tool_name,
                params=obs.params,
                result_summary=obs.summary,
                success=obs.success,
                execution_time_ms=obs.execution_time_ms,
            )
            for i, obs in enumerate(result.observations)
        ]

        # 8. 从观察记录构建证据列表
        evidence = AgenticEngine.build_evidence(result.observations)

        # 9. 从 LLM 答案的 key_issues evidence 引用匹配证据来源
        evidence_citations = []
        for issue in result.answer.key_issues:
            for ev_ref in issue.get("evidence", []):
                if not isinstance(ev_ref, str):
                    continue
                matched_source = "unknown"
                matched_type = "unknown"
                for ev_item in evidence:
                    if (ev_ref in ev_item.summary
                            or ev_ref in ev_item.source_name
                            or ev_item.summary in ev_ref):
                        matched_source = ev_item.source_name
                        matched_type = ev_item.source_type
                        break
                evidence_citations.append(EvidenceCitation(
                    citation=ev_ref,
                    source_type=matched_type,
                    source_id=matched_source,
                ))

        # 10. 事实性查询：key_issues 为空时，自动从 evidence 生成 citations
        if not evidence_citations and evidence:
            for ev_item in evidence:
                evidence_citations.append(EvidenceCitation(
                    citation=ev_item.citation,
                    source_type=ev_item.source_type,
                    source_id=ev_item.source_name,
                ))

        # 11. 保存会话（包含证据和工具追踪）
        conv_manager.add_turn(
            session_id, request.question, analyzed, result.answer,
            evidence=evidence,
            evidence_citations=evidence_citations,
            tool_trace=tool_trace,
            response_type="normal",
        )

        return DecisionResponse(
            domain=domain,
            intent="general",
            session_id=session_id,
            analyzed_query=analyzed,
            evidence=evidence,
            evidence_citations=evidence_citations,
            answer=result.answer,
            tool_trace=tool_trace,
            decision_mode="agentic_rag",
            response_type="normal",
            confidence=result.confidence,
            needs_human_review=result.needs_human_review,
            metadata={
                "total_turns": result.total_turns,
                "total_tool_calls": result.total_tool_calls,
                "total_time_ms": result.total_time_ms,
                "observations_count": len(result.observations),
                "running_summary": result.running_summary,
            },
        )

    def _simple_response(self, intent: str, domain: str,
                         session_id: str, question: str) -> DecisionResponse:
        """简单社交意图的快速响应"""
        text = SIMPLE_DEFAULTS.get(intent, "请问有什么可以帮您的？")
        answer = DecisionAnswer(
            summary=text,
            confidence=1.0,
            confidence_reason="简单社交意图，无需检索",
        )
        analyzed = AnalyzedQuery(domain=domain, intent=intent)
        conv_manager.add_turn(
            session_id, question, analyzed, answer, response_type="simple",
        )
        logger.info(f"[kernel] simple_response intent={intent}")
        return DecisionResponse(
            domain=domain,
            intent=intent,
            session_id=session_id,
            analyzed_query=analyzed,
            answer=answer,
            decision_mode="agentic_rag",
            response_type="simple",
            confidence=1.0,
            needs_human_review=False,
            metadata={},
        )


# 模块级单例
decision_kernel = DecisionKernel()
