"""
记忆提取器 — 使用 LLM 从对话轮次中提取短期记忆和长期记忆候选
"""
import json
import threading
from typing import Dict, List, Optional

from model_management.model_client import get_model_client
from system.logger import logger


class MemoryExtractor:
    """LLM 记忆提取器"""

    def __init__(self):
        self._model_client = None

    @property
    def model_client(self):
        if self._model_client is None:
            self._model_client = get_model_client()
        return self._model_client

    def extract_async(self, question: str, answer_summary: str,
                      session_id: str, domain: str):
        """异步提取记忆（后台线程）"""
        if not self.model_client:
            logger.warning("[memory] LLM 不可用，跳过记忆提取")
            return

        thread = threading.Thread(
            target=self._extract_and_store,
            args=(question, answer_summary, session_id, domain),
            daemon=True,
        )
        thread.start()

    def _extract_and_store(self, question: str, answer_summary: str,
                           session_id: str, domain: str):
        """提取记忆并存储到 MemoryManager"""
        try:
            result = self._call_llm_extract(question, answer_summary)

            if not result:
                return

            # 导入放在这里避免循环依赖
            from decision_engine.memory.memory_manager import memory_manager

            # 存储短期记忆
            short_term = result.get("short_term", [])
            if short_term:
                for entry in short_term:
                    memory_manager.add_short_term(
                        content=entry.get("content", ""),
                        category=entry.get("category", "fact"),
                        importance=entry.get("importance", 0.5),
                        session_id=session_id,
                        domain=domain,
                    )
                logger.info(f"[memory] 提取了 {len(short_term)} 条短期记忆")

            # 合并长期记忆候选
            long_term_candidates = result.get("long_term_candidates", [])
            if long_term_candidates:
                new_prefs = [
                    c["content"] for c in long_term_candidates
                    if c.get("category") == "preference"
                ]
                new_decs = [
                    c["content"] for c in long_term_candidates
                    if c.get("category") == "decision"
                ]
                if new_prefs or new_decs:
                    # 检查是否需要提炼
                    existing = memory_manager.read_long_term_memories() or {
                        "preferences": [], "decisions": []
                    }
                    total = (
                        len(existing["preferences"]) + len(new_prefs) +
                        len(existing["decisions"]) + len(new_decs)
                    )
                    if total > 10:
                        condensed = self._condense_long_term(
                            existing, new_prefs, new_decs
                        )
                        if condensed:
                            memory_manager.write_long_term_memories(
                                condensed["preferences"],
                                condensed["decisions"],
                            )
                            logger.info("[memory] 长期记忆已提炼更新")
                    else:
                        memory_manager.merge_long_term_memories(
                            new_prefs, new_decs
                        )
                        logger.info(
                            f"[memory] 长期记忆候选: "
                            f"偏好={len(new_prefs)}条, 决策={len(new_decs)}条"
                        )

        except Exception as e:
            logger.error(f"[memory] 记忆提取失败: {e}")

    def _call_llm_extract(self, question: str,
                          answer_summary: str) -> Optional[dict]:
        """调用 LLM 提取记忆"""
        import os

        prompt_path = os.path.join(
            os.path.dirname(__file__), "prompts", "prompt_memory_extract.md"
        )
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read()

        user_prompt = f"""用户问题：{question}

系统回答摘要：{answer_summary[:500]}

请分析以上对话，提取需要记住的信息。"""

        try:
            response = self.model_client.call_json(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.3,
                max_tokens=500,
            )
            return response
        except Exception as e:
            logger.error(f"[memory] LLM 提取调用失败: {e}")
            return None

    def _condense_long_term(self, existing: dict,
                            new_prefs: List[str],
                            new_decisions: List[str]) -> Optional[dict]:
        """超限时调用 LLM 提炼合并长期记忆"""
        all_prefs = existing.get("preferences", []) + new_prefs
        all_decs = existing.get("decisions", []) + new_decisions

        prompt = f"""现有长期记忆超限，需要提炼合并。

当前偏好列表（{len(all_prefs)}条）：
{chr(10).join(f'- {p}' for p in all_prefs)}

当前决策列表（{len(all_decs)}条）：
{chr(10).join(f'- {d}' for d in all_decs)}

请提炼合并，保留最重要的信息，控制在10条以内、总计300字以内。
输出 JSON 格式：
{{"preferences": ["合并后的偏好1", "合并后的偏好2"], "decisions": ["合并后的决策1"]}}"""

        try:
            response = self.model_client.call_json(
                prompt=prompt,
                system_prompt="你是一个信息提炼助手，负责合并和精简长期记忆条目。保留最核心、最重要的信息。",
                temperature=0.3,
                max_tokens=400,
            )
            return response
        except Exception as e:
            logger.error(f"[memory] 长期记忆提炼失败: {e}")
            # 降级策略：保留最近的
            return {
                "preferences": all_prefs[-5:],
                "decisions": all_decs[-5:],
            }