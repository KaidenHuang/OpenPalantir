"""
AgenticContext — Agentic 循环的上下文窗口管理

核心策略：
1. 工具结果先截断，再压缩为观察摘要
2. 每 3 条观察压缩为 running_summary，旧观察移出
3. 硬性 token 预算，超出时最旧观察优先淘汰
"""
from typing import List

from decision_engine.agentic.types import Observation
from decision_engine.config import get_config


class AgenticContext:
    """管理 Agentic 循环中的上下文窗口"""

    OBSERVATION_SUMMARY_CHARS = 500

    def __init__(self, question: str, domain: str,
                 entity_types: list = None,
                 history: list = None,
                 memories: list = None,
                 long_term_memories: dict = None):
        self.question = question
        self.domain = domain
        self.entity_types = entity_types or []
        self.history = history or []
        self.memories = memories or []
        self.long_term_memories = long_term_memories or {}
        self.observations: List[Observation] = []
        self.running_summary: str = ""

        # 从配置文件加载上下文管理参数
        cfg = get_config()["context"]
        self.max_observations = cfg["max_observations"]
        self.compress_batch = cfg["compress_batch"]
        self.keep_groups = cfg["keep_groups"]

    def add_observation(self, obs: Observation):
        """添加一条工具调用观察"""
        self.observations.append(obs)

    def compress(self, messages: list) -> list:
        """将最早的观察压缩到 running_summary，重建消息列表

        仅当观察数超过 max_observations 时触发。
        """
        if len(self.observations) <= self.max_observations:
            return messages

        # 取最早的 compress_batch 条进行压缩
        batch = self.compress_batch
        oldest = self.observations[:batch]
        self.observations = self.observations[batch:]

        # 追加到 running_summary
        new_findings = "\n".join(
            f"- [{o.tool_name}] {o.summary}" for o in oldest
        )
        if self.running_summary:
            self.running_summary += f"\n{new_findings}"
        else:
            self.running_summary = f"## 已收集信息摘要\n{new_findings}"

        return self._rebuild_messages(messages)

    def _rebuild_messages(self, messages: list) -> list:
        """用压缩后的上下文重建消息列表"""
        head = messages[:2]  # system + user

        # 构建压缩后的上下文消息
        parts = [f"## 当前信息摘要\n{self.running_summary}"]
        if self.observations:
            parts.append("\n## 最近观察")
            for o in self.observations:
                parts.append(f"- [{o.tool_name}] {o.summary}")

        context_msg = {"role": "system", "content": "\n".join(parts)}

        # 保留最后 N 个完整的 assistant+tool 消息组，避免孤立 tool 消息
        tail = self._extract_complete_groups(messages[2:], keep_groups=self.keep_groups)
        return head + [context_msg] + tail

    @staticmethod
    def _extract_complete_groups(messages: list, keep_groups: int) -> list:
        """从消息列表尾部提取完整的 assistant+tool 消息组

        一个"组"以 assistant 消息开始，后跟其对应的 tool 消息。
        确保不会截断组，避免产生孤立的 tool 消息。
        """
        if not messages:
            return []

        # 从后向前扫描，找到 assistant 消息的边界
        group_starts = []
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "assistant":
                group_starts.append(i)
                if len(group_starts) >= keep_groups:
                    break

        if not group_starts:
            return messages[-keep_groups:] if messages else []

        # 从最早的组开始截取
        cut_index = group_starts[-1]
        return messages[cut_index:]

    def format_history(self) -> str:
        """格式化历史对话，用于 prompt 注入"""
        if not self.history:
            return "（无历史对话）"
        lines = []
        for h in self.history:
            lines.append(f"- 用户: {h.get('question', '')}")
            lines.append(f"- 助手: {h.get('summary', '')}")
        return "\n".join(lines)

    def format_memories(self) -> str:
        """格式化记忆，用于 prompt 注入"""
        parts = []

        if self.memories:
            parts.append("### 短期记忆")
            for m in self.memories:
                content = m.get("content", "") if isinstance(m, dict) else str(m)
                parts.append(f"- {content}")

        if self.long_term_memories:
            prefs = self.long_term_memories.get("preferences", [])
            decs = self.long_term_memories.get("decisions", [])
            if prefs:
                parts.append("### 用户偏好（长期）")
                for p in prefs:
                    parts.append(f"- {p}")
            if decs:
                parts.append("### 重要决策（长期）")
                for d in decs:
                    parts.append(f"- {d}")

        return "\n".join(parts) if parts else "（无记忆）"

    def format_entity_types(self) -> str:
        """格式化领域实体类型，用于 prompt 注入"""
        if not self.entity_types:
            return ""
        lines = ["\n## 领域实体类型\n"]
        for et in self.entity_types:
            if isinstance(et, dict):
                lines.append(f"- **{et['name']}**: {et.get('description', '')}")
            else:
                lines.append(f"- {et}")
        return "\n".join(lines)
