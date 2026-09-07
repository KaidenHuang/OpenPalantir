"""
Agentic 模块特有类型定义
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List

from decision_engine.contracts import DecisionAnswer, RawEvidence


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
class SeedResult:
    """种子检索结果"""
    doc_summaries: List[RawEvidence] = field(default_factory=list)
    db_summaries: List[RawEvidence] = field(default_factory=list)
    related_entities: List[Dict[str, Any]] = field(default_factory=list)
    total_sources: int = 0

    @property
    def is_empty(self) -> bool:
        return (
            not self.doc_summaries
            and not self.db_summaries
            and not self.related_entities
        )

    def format_for_prompt(self) -> str:
        """格式化为可注入 system prompt 的文本"""
        if self.is_empty:
            return ""

        sections = ["## 初始检索结果（自动获取）\n"]

        if self.doc_summaries:
            sections.append(f"### 相关文档摘要 ({len(self.doc_summaries)} 条)")
            for ev in self.doc_summaries:
                name = ev.content.get("summary", ev.source_id)[:80]
                uri = ev.metadata.get("datasource", "")
                sections.append(f"- **{ev.source_id}**: {name} [{uri}]")
            sections.append("")

        if self.db_summaries:
            sections.append(f"### 相关数据库概要 ({len(self.db_summaries)} 条)")
            for ev in self.db_summaries:
                table = ev.content.get("table_name", ev.source_id)
                uri = ev.metadata.get("datasource", "")
                row_count = ev.content.get("row_count", "")
                desc = f"{table} 表"
                if row_count:
                    desc += f"，{row_count}条"
                sections.append(f"- **{desc}** [{uri}]")
            sections.append("")

        if self.related_entities:
            sections.append(f"### 相关图谱实体 ({len(self.related_entities)} 个)")
            for ent in self.related_entities[:10]:
                name = ent.get("name", ent.get("id", "?"))
                etype = ent.get("type", "entity")
                desc = ent.get("description", "")
                line = f"- {name} ({etype})"
                if desc:
                    line += f": {desc[:80]}"
                sections.append(line)
            if len(self.related_entities) > 10:
                sections.append(f"- ... 还有 {len(self.related_entities) - 10} 个实体")
            sections.append("")

        sections.append("> 如需更多信息，请使用工具进一步检索和分析。")
        return "\n".join(sections)


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
