"""
MultiAgentEngine — 多 Agent 协作引擎

将复杂问题分解为多个子任务，由专职 Agent 协作完成：
- Planner Agent：分解问题为子任务
- Researcher Agent：信息检索（种子检索 + 工具调用）
- Analyst Agent：图谱分析（路径/社区/中心性）
- Critic Agent：结果校验与反驳

支持两种协作模式：
- 链式（chain）：Planner → Researcher → Analyst → Critic → 综合
- 反思（reflect）：单 Agent 回答后由 Critic 校验，不一致时修正
"""
import json
import time
from typing import Optional

from decision_engine.agentic.engine import AgenticEngine
from decision_engine.agentic.tools import ToolRegistry
from decision_engine.agentic.types import AgenticResult, Observation
from decision_engine.contracts import DecisionAnswer
from model_management.model_client import get_model_client
from system.logger import logger


# ── 子 Agent 角色 Prompt ──────────────────────────────────

_PLANNER_PROMPT = """你是一个任务规划专家。你的职责是将复杂的分析问题分解为可执行的子任务。

给定用户问题，请输出 JSON 格式的任务分解：
```json
{{
  "analysis": "对问题的分析（1-2句）",
  "sub_tasks": [
    {{"id": 1, "type": "research", "description": "需要检索的信息", "query": "具体查询内容"}},
    {{"id": 2, "type": "analyze", "description": "需要的分析", "query": "具体分析内容"}}
  ],
  "mode": "chain"
}}
```

规则：
- sub_tasks 最多 4 个
- type 只能是 "research"（信息检索）或 "analyze"（图谱分析）
- 如果问题简单，只生成 1 个 sub_task，mode 设为 "simple"
- 不要编造数据，只描述需要什么"""

_CRITIC_PROMPT = """你是一个严谨的审核专家。你的职责是校验答案的准确性和完整性。

给定用户问题和初步答案，请评估：
```json
{{
  "valid": true/false,
  "issues": ["发现的问题1", "发现的问题2"],
  "confidence_adjust": 0.0,
  "suggestion": "改进建议（如果 valid=false）"
}}
```

规则：
- 检查答案是否包含具体数据（而非泛泛而谈）
- 检查是否引用了实际证据
- 检查置信度评估是否合理
- 如果答案质量高，valid=true，confidence_adjust=0
- 如果发现幻觉或编造数据，valid=false，confidence_adjust=-0.3"""


class MultiAgentEngine:
    """多 Agent 协作引擎"""

    # 置信度低于此阈值时触发 Critic 校验
    CRITIC_THRESHOLD = 0.6

    def __init__(self, tool_registry: ToolRegistry, model_client=None):
        self.tools = tool_registry
        self.llm = model_client or get_model_client()
        self._single_engine = AgenticEngine(tool_registry, self.llm)

    def run(self, question: str, domain: str,
            entity_types: list = None,
            history: list = None,
            memories: list = None,
            long_term_memories: dict = None) -> AgenticResult:
        """主入口：先单 Agent 执行，低置信度时触发 Critic 校验"""
        start_time = time.time()

        # Phase 1: 单 Agent 执行
        logger.info("[multi_agent] Phase 1: 单 Agent 执行")
        result = self._single_engine.run(
            question=question,
            domain=domain,
            entity_types=entity_types,
            history=history,
            memories=memories,
            long_term_memories=long_term_memories,
        )

        # Phase 2: 低置信度时触发 Critic 校验
        if result.confidence < self.CRITIC_THRESHOLD and result.total_tool_calls > 0:
            logger.info(
                f"[multi_agent] Phase 2: 置信度 {result.confidence:.2f} "
                f"< {self.CRITIC_THRESHOLD}，触发 Critic 校验"
            )
            result = self._critic_review(question, result)

        total_ms = (time.time() - start_time) * 1000
        result.total_time_ms = total_ms
        return result

    def _critic_review(self, question: str, result: AgenticResult) -> AgenticResult:
        """Critic Agent 校验结果，必要时降低置信度"""
        try:
            # 构造 Critic 输入
            answer_text = result.answer.summary
            if result.answer.situation_analysis:
                answer_text += "\n\n" + result.answer.situation_analysis

            # 收集证据摘要
            evidence_summary = ""
            for obs in result.observations[:5]:
                evidence_summary += f"- [{obs.tool_name}] {obs.summary}\n"

            critic_input = (
                f"用户问题：{question}\n\n"
                f"初步答案：{answer_text}\n\n"
                f"已收集证据：\n{evidence_summary}\n\n"
                f"当前置信度：{result.confidence:.2f}（理由：{result.confidence_reason}）\n\n"
                f"请审核答案的准确性和完整性。"
            )

            messages = [
                {"role": "system", "content": _CRITIC_PROMPT},
                {"role": "user", "content": critic_input},
            ]

            response = self.llm.call_with_tools(messages=messages, tools=[])
            if response is None:
                return result

            content = response.get("content", "")
            critic_result = self._parse_critic(content)

            if critic_result is None:
                logger.warning("[multi_agent] Critic 返回无法解析，保持原结果")
                return result

            # 应用 Critic 反馈
            if not critic_result.get("valid", True):
                adjust = critic_result.get("confidence_adjust", 0)
                new_confidence = max(0.0, result.confidence + adjust)
                issues = critic_result.get("issues", [])
                suggestion = critic_result.get("suggestion", "")

                logger.info(
                    f"[multi_agent] Critic 发现问题: {issues}, "
                    f"置信度调整: {result.confidence:.2f} → {new_confidence:.2f}"
                )

                # 标记需要人工审核
                result.confidence = new_confidence
                result.confidence_reason = (
                    f"{result.confidence_reason}；"
                    f"Critic 审核: {'; '.join(issues[:3])}"
                )
                result.needs_human_review = True

                # 将 Critic 建议追加到 answer 的 situation_analysis
                if suggestion:
                    result.answer.situation_analysis += f"\n\n[审核建议] {suggestion}"

            else:
                logger.info("[multi_agent] Critic 审核通过")

            return result

        except Exception as e:
            logger.warning(f"[multi_agent] Critic 校验失败（降级为原结果）: {e}")
            return result

    @staticmethod
    def _parse_critic(content: str) -> Optional[dict]:
        """解析 Critic Agent 的 JSON 输出"""
        from utils.json_utils import extract_json
        return extract_json(content)
