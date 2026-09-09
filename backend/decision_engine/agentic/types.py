"""
Agentic 模块特有类型定义
"""
from dataclasses import dataclass
from typing import List

from decision_engine.contracts import DecisionAnswer


@dataclass
class Observation:
    """单次工具调用的观察记录"""
    tool_name: str
    params: dict
    summary: str                          # 压缩后的摘要，≤500 字符
    full_result: dict                     # 完整结果（不放入上下文）
    tool_call_id: str
    execution_time_ms: float
    success: bool


@dataclass
class AgenticResult:
    """Agentic 循环的最终输出"""
    answer: DecisionAnswer
    confidence: float                # 0.0-1.0
    confidence_reason: str           # 置信度理由
    observations: List[Observation]
    total_turns: int
    total_tool_calls: int
    total_time_ms: float
    needs_human_review: bool
    running_summary: str             # 压缩后的观察历史
