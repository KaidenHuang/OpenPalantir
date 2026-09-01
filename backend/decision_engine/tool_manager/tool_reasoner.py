"""
ToolReasoner 多轮推理引擎

核心循环：LLM 推理 → 调用工具（Skill / MCP）→ 获取结果 → 继续推理 → 最终输出 DecisionAnswer。
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from model_management.model_client import get_model_client, ModelClient
from decision_engine.contracts import DecisionAnswer, ToolTrace, WorkOrder
from decision_engine.tool_manager.skill.skill_registry import SkillRegistry, SkillResult
from system.logger import logger

if TYPE_CHECKING:
    from decision_engine.tool_manager.mcp.mcp_manager import MCPManager

MAX_TURNS = 10
MAX_RESULT_CHARS = 4000


@dataclass
class ToolReasoningResult:
    """多轮推理的完整结果"""
    answer: DecisionAnswer
    tool_traces: List[ToolTrace] = field(default_factory=list)
    total_turns: int = 0
    total_tool_calls: int = 0
    total_time_ms: float = 0.0


class ToolReasoner:
    """多轮 LLM + 工具推理引擎

    核心循环：
        1. 发送 messages + tools 到 LLM
        2. 如果 LLM 返回 tool_calls → 执行工具（本地 Skill 或 MCP）→ 追加结果 → 回到步骤 1
        3. 如果 LLM 返回纯文本 → 解析为 DecisionAnswer → 结束
    """

    _system_prompt: str = ""

    def __init__(
        self,
        skill_registry: SkillRegistry,
        model_client: Optional[ModelClient] = None,
        mcp_manager: Optional["MCPManager"] = None,
    ):
        self.skill_registry = skill_registry
        self.model_client = model_client or get_model_client()
        self.mcp_manager = mcp_manager  # MCPManager 实例，可选

    @classmethod
    def _load_system_prompt(cls) -> str:
        if not cls._system_prompt:
            path = os.path.join(
                os.path.dirname(__file__), "prompts", "prompt_tool_reasoning.md"
            )
            with open(path, "r", encoding="utf-8") as f:
                cls._system_prompt = f.read()
        return cls._system_prompt

    def reason(
        self,
        question: str,
        domain: str,
        initial_context: Optional[Dict[str, Any]] = None,
        max_turns: int = MAX_TURNS,
    ) -> ToolReasoningResult:
        """执行多轮工具推理"""
        overall_start = time.time()
        tools = self.skill_registry.get_tool_definitions(domain)
        skill_defs = self.skill_registry.get_skill_definitions(domain)

        # 合并 MCP 工具
        if self.mcp_manager:
            mcp_tools = self.mcp_manager.get_tool_definitions()
            tools = tools + mcp_tools

        if not tools:
            logger.warning(f"[tool_reasoner] domain '{domain}' 没有可用工具")
            return ToolReasoningResult(
                answer=DecisionAnswer(
                    summary="当前域没有可用的工具",
                    situation_analysis="工具推理模式需要至少一个可用的工具。",
                ),
                total_time_ms=(time.time() - overall_start) * 1000,
            )

        # 构建 system prompt（包含 Skill 和 MCP 工具描述）
        system_prompt = self._build_system_prompt(domain, skill_defs)

        # 初始化消息列表
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        if initial_context:
            ctx_str = json.dumps(initial_context, ensure_ascii=False, indent=2)
            messages.append({
                "role": "system",
                "content": f"以下是预处理阶段获取的初始上下文，可作为推理起点：\n```json\n{ctx_str}\n```",
            })

        messages.append({"role": "user", "content": question})

        tool_traces: List[ToolTrace] = []
        total_tool_calls = 0

        for turn in range(max_turns):
            logger.info(f"[tool_reasoner] turn {turn + 1}/{max_turns}")

            if self.model_client is None:
                logger.warning("[tool_reasoner] LLM 不可用")
                break

            response = self.model_client.call_with_tools(
                messages=messages,
                tools=tools,
            )

            if response is None:
                logger.warning("[tool_reasoner] LLM 返回 None")
                break

            assistant_content = response.get("content", "") or ""
            tool_calls = response.get("tool_calls", []) or []

            # 无 tool_calls → LLM 给出最终答案
            if not tool_calls:
                answer = self._parse_final_answer(assistant_content)
                total_time = (time.time() - overall_start) * 1000
                return ToolReasoningResult(
                    answer=answer,
                    tool_traces=tool_traces,
                    total_turns=turn + 1,
                    total_tool_calls=total_tool_calls,
                    total_time_ms=total_time,
                )

            # 有 tool_calls → 执行工具
            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": assistant_content}
            if self._supports_native_tool_calls():
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            for tc in tool_calls:
                fn_info = tc.get("function", {})
                fn_name = fn_info.get("name", "")
                fn_args_str = fn_info.get("arguments", "{}")
                tc_id = tc.get("id", f"call_{turn}_{fn_name}")

                # 解析参数
                try:
                    fn_args = json.loads(fn_args_str) if isinstance(fn_args_str, str) else fn_args_str
                except json.JSONDecodeError:
                    fn_args = {}

                # 按来源路由执行
                if self.mcp_manager and self.mcp_manager.is_mcp_tool(fn_name):
                    logger.info(
                        f"[tool_reasoner] 调用 MCP 工具 '{fn_name}' "
                        f"参数: {json.dumps(fn_args, ensure_ascii=False)[:200]}"
                    )
                    mcp_result = self.mcp_manager.execute(fn_name, fn_args)
                    success = mcp_result.get("success", False)
                    tool_content = (
                        json.dumps(mcp_result.get("data"), ensure_ascii=False)
                        if success
                        else f"Error: {mcp_result.get('error', '')}"
                    )
                    total_tool_calls += 1
                    tool_traces.append(ToolTrace(
                        step=len(tool_traces) + 1,
                        skill_name=fn_name,
                        params=fn_args,
                        result_summary=self._summarize_mcp_result(mcp_result),
                        success=success,
                        execution_time_ms=0.0,
                    ))
                else:
                    logger.info(
                        f"[tool_reasoner] 调用 Skill '{fn_name}' "
                        f"参数: {json.dumps(fn_args, ensure_ascii=False)[:200]}"
                    )
                    result: SkillResult = self.skill_registry.execute(fn_name, fn_args)
                    total_tool_calls += 1

                    tool_traces.append(ToolTrace(
                        step=len(tool_traces) + 1,
                        skill_name=fn_name,
                        params=fn_args,
                        result_summary=self._summarize_result(result),
                        success=result.success,
                        execution_time_ms=result.execution_time_ms,
                    ))

                    tool_content = (
                        json.dumps(result.data, ensure_ascii=False)
                        if result.success
                        else f"Error: {result.error}"
                    )

                if len(tool_content) > MAX_RESULT_CHARS:
                    tool_content = (
                        tool_content[:MAX_RESULT_CHARS]
                        + f"\n...(截断，原始长度 {len(tool_content)} 字符)"
                    )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": tool_content,
                })

        # 达到最大轮数，强制要求 LLM 总结
        logger.warning(f"[tool_reasoner] 达到最大轮数 {max_turns}，强制总结")
        messages.append({
            "role": "user",
            "content": "你已经收集了足够的信息。请基于以上所有工具执行结果，直接给出最终 JSON 格式的决策建议。",
        })
        if self.model_client:
            final_response = self.model_client.call_with_tools(messages=messages, tools=tools)
            answer = self._parse_final_answer(
                final_response.get("content", "") if final_response else ""
            )
        else:
            answer = DecisionAnswer(summary="LLM 不可用，无法完成推理")

        total_time = (time.time() - overall_start) * 1000
        return ToolReasoningResult(
            answer=answer,
            tool_traces=tool_traces,
            total_turns=max_turns,
            total_tool_calls=total_tool_calls,
            total_time_ms=total_time,
        )

    def _build_system_prompt(self, domain: str, skill_defs: list) -> str:
        """构建包含工具描述的系统提示词"""
        template = self._load_system_prompt()
        tools_desc = "\n".join(
            f"- **{s.name}**: {s.description}\n"
            f"  参数: {json.dumps([{'name': p.name, 'type': p.type, 'description': p.description, 'required': p.required} for p in s.parameters], ensure_ascii=False)}"
            for s in skill_defs
        )
        # 追加 MCP 工具描述
        if self.mcp_manager:
            mcp_desc = self.mcp_manager.get_tool_descriptions()
            if mcp_desc:
                tools_desc += "\n" + mcp_desc
        return template.format(domain=domain, available_tools=tools_desc)

    @staticmethod
    def _parse_final_answer(content: str) -> DecisionAnswer:
        """从 LLM 最终输出解析 DecisionAnswer"""
        try:
            json_str = content
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0]
            data = json.loads(json_str.strip())
            return DecisionAnswer.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[tool_reasoner] 最终答案解析失败: {e}")
            return DecisionAnswer(
                summary="推理完成",
                situation_analysis=content[:2000],
                recommendation=content[:500],
            )

    def _supports_native_tool_calls(self) -> bool:
        """判断当前模型是否支持原生 tool_calls"""
        if self.model_client is None:
            return False
        return self.model_client.config.type == "cloud"

    @staticmethod
    def _summarize_result(result: SkillResult) -> str:
        """生成 Skill 结果的简短摘要"""
        if not result.success:
            return f"执行失败: {result.error}"
        data = result.data
        if isinstance(data, dict):
            if "entities" in data:
                return f"返回 {len(data['entities'])} 个实体"
            if "total_paths" in data:
                paths = data.get("paths", [])
                return f"找到 {data['total_paths']} 条路径"
            if "communities" in data:
                return f"检测到 {data.get('total_communities', len(data['communities']))} 个社区"
            if "documents" in data:
                return f"找到 {len(data['documents'])} 篇文档"
            if "tables" in data:
                return f"找到 {len(data['tables'])} 个表"
            if "found" in data:
                return "找到实体" if data["found"] else "未找到实体"
            if "top_nodes" in data:
                return f"分析 {data.get('total_nodes', 0)} 个节点"
            if "relations" in data:
                return f"返回 {data.get('total_relations', len(data['relations']))} 条关系"
            return f"返回 {len(data)} 个字段"
        if isinstance(data, list):
            return f"返回 {len(data)} 条结果"
        return f"返回 {type(data).__name__} 类型结果"

    @staticmethod
    def _summarize_mcp_result(result: dict) -> str:
        """生成 MCP 工具结果的简短摘要"""
        if not result.get("success"):
            return f"执行失败: {result.get('error', '')}"
        data = result.get("data", {})
        if isinstance(data, dict):
            return f"返回 {len(data)} 个字段"
        if isinstance(data, list):
            return f"返回 {len(data)} 条结果"
        if isinstance(data, str):
            return f"返回文本 ({len(data)} 字符)"
        return f"返回 {type(data).__name__} 类型结果"