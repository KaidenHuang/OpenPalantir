"""
AgenticEngine — 统一的 Agentic RAG 引擎

一个 ReAct 循环处理所有场景：
- 简单查询 → 1 轮即答
- 复杂分析 → 多轮检索 + 分析 + 反思
"""
import json
import os
import time
from typing import Dict, List, Optional, Tuple

from decision_engine.agentic.context import AgenticContext
from decision_engine.agentic.tools import ToolRegistry
from decision_engine.agentic.types import AgenticResult, Observation
from decision_engine.config import get_config
from decision_engine.contracts import DecisionAnswer
from model_management.model_client import get_model_client
from system.logger import logger


# 简单意图关键词映射
_SIMPLE_PATTERNS = {
    "greeting": ["你好", "您好", "hello", "hi", "嗨", "早上好", "下午好", "晚上好"],
    "identity": ["你是谁", "你叫什么", "你是什么", "介绍一下自己"],
    "capability": ["你能做什么", "你会什么", "你有什么功能", "帮我什么"],
    "farewell": ["再见", "拜拜", "bye", "下次见"],
    "thanks": ["谢谢", "感谢", "多谢", "thanks", "thank you"],
}

SIMPLE_DEFAULTS: Dict[str, str] = {
    "greeting": "您好！我是智能决策助手，请问有什么可以帮您的？",
    "identity": "我是智能决策助手，专注于数据分析和决策支持。",
    "capability": (
        "我可以帮您分析知识图谱、检索文档和数据库、提供决策建议和行动方案。"
        "请问您想了解什么？"
    ),
    "farewell": "再见！如有需要随时找我。",
    "thanks": "不客气！如有其他问题，随时告诉我。",
}


def quick_check_intent(question: str) -> str:
    """快速规则匹配，判断是否为简单社交意图。返回意图名或 'complex'"""
    q = question.strip().lower()
    for intent, patterns in _SIMPLE_PATTERNS.items():
        for p in patterns:
            if p in q:
                return intent
    return "complex"



class AgenticEngine:
    """统一的 Agentic RAG 引擎"""

    OBSERVATION_MAX_CHARS = 500

    def __init__(self, tool_registry: ToolRegistry, model_client=None):
        self.tools = tool_registry
        self.llm = model_client or get_model_client()
        self._prompt_template = self._load_prompt_template()

        # 从配置文件加载上限参数
        cfg = get_config()
        agentic_cfg = cfg["agentic"]
        self.max_turns = agentic_cfg["max_turns"]
        self.max_result_chars = agentic_cfg["max_result_chars"]
        self.confidence_threshold = agentic_cfg["confidence_threshold"]
        self._synthesis_cfg = cfg["forced_synthesis"]

    def run(self, question: str, domain: str,
            entity_types: list = None,
            history: list = None,
            memories: list = None,
            long_term_memories: dict = None) -> AgenticResult:
        """主入口：构建上下文 → Agentic 循环"""
        start_time = time.time()

        ctx = AgenticContext(
            question=question,
            domain=domain,
            entity_types=entity_types or [],
            history=history or [],
            memories=memories or [],
            long_term_memories=long_term_memories or {},
        )

        # Phase B: 构建 system prompt
        tool_defs = self.tools.get_definitions(domain)

        # 空工具快速失败：避免发送注定无法调用工具的 LLM 请求
        if not tool_defs:
            logger.warning("[agentic] 无可用工具，返回降级响应")
            return AgenticResult(
                answer=DecisionAnswer(
                    summary="系统暂无可用工具，无法检索数据。请检查 Skill 和 MCP 配置。",
                    confidence=0.1,
                    confidence_reason="无可用工具",
                ),
                confidence=0.1,
                confidence_reason="无可用工具",
                observations=[],
                total_turns=0,
                total_tool_calls=0,
                total_time_ms=(time.time() - start_time) * 1000,
                needs_human_review=True,
                running_summary="",
            )

        system_prompt = self._build_system_prompt(ctx, tool_defs)

        # Phase C: Agentic 循环
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]

        tool_calls_count = 0

        for turn in range(self.max_turns):
            logger.info(f"[agentic] turn {turn + 1}/{self.max_turns}")

            response = self.llm.call_with_tools(
                messages=messages,
                tools=tool_defs,
            )

            if response is None:
                logger.warning("[agentic] LLM 返回 None，提前退出")
                break

            tool_calls = response.get("tool_calls", []) or []

            # 无 tool_calls → LLM 认为信息足够，给出最终答案
            if not tool_calls:
                answer, confidence, conf_reason = self._parse_final(response)
                total_ms = (time.time() - start_time) * 1000
                logger.info(
                    f"[agentic] 完成: {turn + 1} 轮, "
                    f"{tool_calls_count} 次工具调用, "
                    f"置信度={confidence:.2f}, "
                    f"{total_ms:.0f}ms"
                )
                return AgenticResult(
                    answer=answer,
                    confidence=confidence,
                    confidence_reason=conf_reason,
                    observations=ctx.observations,
                    total_turns=turn + 1,
                    total_tool_calls=tool_calls_count,
                    total_time_ms=total_ms,
                    needs_human_review=confidence < self.confidence_threshold,
                    running_summary=ctx.running_summary,
                )

            # 执行工具调用
            assistant_msg = {
                "role": "assistant",
                "content": response.get("content", ""),
            }
            if self._supports_native_tools():
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            for tc in tool_calls:
                obs = self._execute_tool_call(tc)
                ctx.add_observation(obs)
                tool_calls_count += 1
                # 传完整结果 JSON（截断到 max_result_chars），让 LLM 获得充分数据
                result_text = json.dumps(obs.full_result, ensure_ascii=False, default=str)
                if len(result_text) > self.max_result_chars:
                    result_text = result_text[:self.max_result_chars] + "...(truncated)"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_text,
                })

            # 尝试压缩上下文（compress 内部判断是否触发）
            messages = ctx.compress(messages)

            # 每 2 轮插入反思提示
            if turn > 0 and turn % 2 == 0:
                messages.append({
                    "role": "system",
                    "content": (
                        "请反思：当前收集的信息是否足以回答用户问题？"
                        "如果足够，请直接给出最终 JSON 答案。"
                        "如果不足，请说明还需要什么信息并继续调用工具。"
                    ),
                })

        # 达到最大轮数，强制综合
        # 汇总已收集的工具调用信息，帮助 LLM 基于现有数据作答
        synth_cfg = self._synthesis_cfg
        tool_summary_parts = []
        for obs in ctx.observations:
            result_preview = json.dumps(
                obs.full_result, ensure_ascii=False, default=str,
            )[:synth_cfg["preview_chars"]]
            tool_summary_parts.append(f"- [{obs.tool_name}] {result_preview}")
        tool_summary = "\n".join(tool_summary_parts[:synth_cfg["max_items"]])

        messages.append({
            "role": "system",
            "content": (
                "已达到最大工具调用次数，不能再调用工具。\n"
                "以下是已收集的工具调用结果：\n"
                f"{tool_summary}\n\n"
                "请基于以上数据直接给出最终 JSON 答案。"
                "如果数据中有 total_count 或 sample_neighbors，请据此回答统计类问题。"
                "不要再调用任何工具。"
            ),
        })
        final = self.llm.call_with_tools(messages=messages, tools=tool_defs)
        answer, confidence, conf_reason = self._parse_final(final)
        total_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[agentic] 强制综合: {self.max_turns} 轮, "
            f"{tool_calls_count} 次工具调用, "
            f"置信度={confidence:.2f}, {total_ms:.0f}ms"
        )
        return AgenticResult(
            answer=answer,
            confidence=min(confidence, 0.5),
            confidence_reason=conf_reason + "（达到最大轮数，强制综合）",
            observations=ctx.observations,
            total_turns=self.max_turns,
            total_tool_calls=tool_calls_count,
            total_time_ms=total_ms,
            needs_human_review=True,
            running_summary=ctx.running_summary,
        )

    # ── 工具执行 ────────────────────────────────────────

    def _execute_tool_call(self, tc: dict) -> Observation:
        """解析并执行一个 tool_call"""
        func = tc.get("function", {})
        name = func.get("name", "unknown")
        raw_args = func.get("arguments", "{}")

        try:
            params = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            params = {}

        logger.info(f"[agentic] 调用工具: {name}({json.dumps(params, ensure_ascii=False)[:100]})")
        obs = self.tools.execute(name, params)
        obs.tool_call_id = tc.get("id", "")
        return obs

    # ── 最终答案解析 ────────────────────────────────────

    def _parse_final(self, response: Optional[dict]) -> Tuple[DecisionAnswer, float, str]:
        """从 LLM 最终响应中解析 DecisionAnswer + 置信度"""
        if response is None:
            return (
                DecisionAnswer(summary="系统未能生成有效回答，请重试。"),
                0.3,
                "LLM 返回空响应",
            )

        content = response.get("content", "")
        if not content:
            return (
                DecisionAnswer(summary="系统未能生成有效回答，请重试。"),
                0.3,
                "LLM 内容为空",
            )

        # 尝试解析 JSON
        data = self._extract_json(content)
        if data is None:
            # 安全网：检测 LLM 输出的元评论（描述问题类型而非实际回答）
            meta_patterns = [
                "事实性查询", "事实性数据", "直接回答即可", "不需要使用工具",
                "无需检索", "无需调用工具", "可以直接回答",
                "根据历史对话", "此前已确认", "历史上下文",
                "已完整列出", "如上所述", "如前所述",
                "无可用工具", "无法访问真实数据", "没有任何可用工具",
                "Let me try", "let me try", "I need to",
                "Let me check", "let me check",
            ]
            stripped = content.strip()
            # 只有内容短（< 200 字符）且包含元评论关键词时才判定
            is_meta = len(stripped) < 200 and any(p in content for p in meta_patterns)
            if is_meta:
                logger.warning(f"[agentic] LLM 输出元评论而非实际回答: {content[:100]}")
                return (
                    DecisionAnswer(summary="系统未能获取到具体数据，请尝试重新提问。"),
                    0.2,
                    "LLM 输出元评论，未提供实际数据",
                )
            return (
                DecisionAnswer(summary=content[:self._synthesis_cfg["raw_fallback_chars"]]),
                0.4,
                "无法解析为结构化 JSON，返回原始文本",
            )

        # 委托给 DecisionAnswer.from_dict（处理 WorkOrder、dict 类型字段等）
        answer = DecisionAnswer.from_dict(data)
        conf_reason = answer.confidence_reason or "未提供置信度理由"

        # 检测答案是否在引用历史而非给出具体数据
        history_refs = ["根据历史对话", "此前已确认", "历史上下文", "已完整列出", "如上所述"]
        if any(ref in answer.summary for ref in history_refs):
            logger.warning(f"[agentic] 答案引用历史而非工具数据: {answer.summary[:80]}")
            answer.confidence = min(answer.confidence, 0.3)
            conf_reason = "答案基于历史对话而非实时工具检索"

        return answer, answer.confidence, conf_reason

    def _extract_json(self, content: str) -> Optional[dict]:
        """从 LLM 输出中提取 JSON（委托给统一工具）"""
        from utils.json_utils import extract_json
        return extract_json(content)

    # ── 证据构建 ────────────────────────────────────────

    @staticmethod
    def build_evidence(observations: List[Observation]) -> list:
        """将工具观察记录转换为 EvidenceItem 列表"""
        from decision_engine.contracts import EvidenceItem

        evidence = []
        for i, obs in enumerate(observations):
            if not obs.success:
                continue
            payload = obs.full_result if isinstance(obs.full_result, dict) else {}
            source_name = obs.params.get(
                "query", obs.params.get("name", obs.params.get("entity_name", obs.tool_name))
            )
            evidence.append(EvidenceItem(
                evidence_id=f"obs_{i + 1}",
                source_type=obs.tool_name,
                source_name=str(source_name)[:80],
                summary=obs.summary,
                payload=payload,
                relevance_score=1.0,
                citation=f"[{obs.tool_name}] {obs.summary[:60]}",
            ))
        return evidence

    # ── System Prompt 构建 ──────────────────────────────

    def _build_system_prompt(self, ctx: AgenticContext, tool_defs: list = None) -> str:
        """构建完整的 system prompt"""
        if tool_defs is None:
            tool_defs = self.tools.get_definitions(ctx.domain)
        tool_desc = self._format_tool_descriptions(tool_defs)

        prompt = self._prompt_template.format(
            domain=ctx.domain,
            entity_types_section=ctx.format_entity_types(),
            tool_descriptions=tool_desc,
            history=ctx.format_history(),
            memories=ctx.format_memories(),
        )
        return prompt

    def _format_tool_descriptions(self, tool_defs: list) -> str:
        """将 OpenAI tools 定义格式化为可读文本"""
        if not tool_defs:
            return "（无可用工具）"
        lines = []
        for t in tool_defs:
            func = t.get("function", {})
            name = func.get("name", "?")
            desc = func.get("description", "无描述")
            params = func.get("parameters", {}).get("properties", {})
            param_names = list(params.keys())
            lines.append(f"- **{name}**: {desc}  参数: {', '.join(param_names)}")
        return "\n".join(lines)

    def _load_prompt_template(self) -> str:
        """加载 prompt 模板文件"""
        prompt_path = os.path.join(
            os.path.dirname(__file__), "prompts", "prompt_agentic.md",
        )
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            logger.error(f"[agentic] prompt 模板文件不存在: {prompt_path}")
            return "你是一个 AI 决策分析师。请根据用户问题给出 JSON 格式的回答。"

    def _supports_native_tools(self) -> bool:
        """检查当前 LLM 是否支持原生 tool calling"""
        if self.llm and hasattr(self.llm, "_supports_tools"):
            return self.llm._supports_tools
        return True
