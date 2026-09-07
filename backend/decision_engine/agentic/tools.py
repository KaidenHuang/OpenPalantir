"""
ToolRegistry — 统一的工具注册表

Skill + MCP 全部统一为 OpenAI function-calling 格式。
LLM 不知道也不关心工具来自哪里。
"""
import json
import time
from typing import Any

from decision_engine.agentic.types import Observation
from system.logger import logger


class ToolRegistry:
    """统一的工具注册表 — Skill + MCP"""

    def __init__(self, skill_registry, mcp_manager=None):
        self._skill_registry = skill_registry
        self._mcp_manager = mcp_manager

    def get_definitions(self, domain: str) -> list:
        """获取 OpenAI 兼容的 tools 列表"""
        tools = []
        try:
            tools = self._skill_registry.get_tool_definitions(domain)
        except Exception as e:
            logger.warning(f"[tools] Skill 工具加载失败: {e}")

        if self._mcp_manager:
            try:
                tools += self._mcp_manager.get_tool_definitions()
            except Exception as e:
                logger.warning(f"[tools] MCP 工具加载失败: {e}")

        return tools

    def execute(self, name: str, params: dict) -> Observation:
        """执行工具，统一返回 Observation"""
        start = time.time()
        tool_call_id = ""

        try:
            if self._mcp_manager and self._is_mcp_tool(name):
                result = self._mcp_manager.execute(name, params)
                summary = self._summarize_mcp(result)
            else:
                result = self._skill_registry.execute(name, params)
                # 委托给 Skill.summarize → SkillResult.summarize
                skill = self._skill_registry.get(name)
                if skill and hasattr(result, "summarize"):
                    summary = skill.summarize(result)
                else:
                    summary = self._summarize_generic(result)
            success = True
        except Exception as e:
            logger.error(f"[tools] 工具 {name} 执行失败: {e}")
            result = {"error": str(e), "success": False}
            summary = f"工具执行失败: {e}"
            success = False

        elapsed = (time.time() - start) * 1000

        return Observation(
            tool_name=name,
            params=params,
            summary=summary,
            full_result=result if isinstance(result, dict) else {"data": str(result)},
            tool_call_id=tool_call_id,
            execution_time_ms=elapsed,
            success=success,
        )

    def _is_mcp_tool(self, name: str) -> bool:
        """判断是否为 MCP 工具（命名格式：{server}__{tool}）"""
        if self._mcp_manager and hasattr(self._mcp_manager, "is_mcp_tool"):
            return self._mcp_manager.is_mcp_tool(name)
        return "__" in name

    def _summarize_mcp(self, result: Any) -> str:
        """MCP 工具结果摘要（MCP 返回 dict）"""
        if not result:
            return "（无结果）"
        if isinstance(result, dict):
            if result.get("error"):
                return f"工具执行失败: {result['error']}"
            if "data" in result:
                data = result["data"]
                if isinstance(data, list):
                    return f"返回 {len(data)} 条记录"
                text = str(data)
                return text[:497] + "..." if len(text) > 500 else text
        return self._summarize_generic(result)

    @staticmethod
    def _summarize_generic(result: Any) -> str:
        """通用兜底摘要"""
        if not result:
            return "（无结果）"
        text = str(result)
        return text[:497] + "..." if len(text) > 500 else text
