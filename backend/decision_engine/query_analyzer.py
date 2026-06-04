import os
from typing import Dict, List, Optional

from model_management.model_client import get_model_client
from system.logger import logger
from decision_engine.contracts import AnalyzedQuery


class QueryAnalyzer:
    _prompt: str = ""

    @classmethod
    def _load_prompt(cls) -> str:
        if not cls._prompt:
            path = os.path.join(os.path.dirname(__file__), "prompts", "prompt_query_analyze.md")
            with open(path, "r", encoding="utf-8") as f:
                cls._prompt = f.read()
        return cls._prompt

    def analyze(self, question: str, history: Optional[List[Dict]] = None) -> AnalyzedQuery:
        client = get_model_client()
        if not client:
            logger.warning("[query_analyzer] LLM unavailable, using fallback")
            return self._fallback(question)

        prompt = self._load_prompt().format(question=question)
        response = client.call_json(prompt=prompt, system_prompt="你是一个查询分析助手，只输出JSON。")
        if response:
            try:
                # 解析新 entities 格式：[{"name": "技术部", "type": "organization", "generalized": "部门"}, ...]
                raw_entities = response.get("entities", [])
                entity_names: List[str] = []
                entity_types: Dict[str, str] = {}
                if isinstance(raw_entities, list):
                    for ent in raw_entities:
                        if isinstance(ent, dict):
                            name = ent.get("name", "")
                            typ = ent.get("type", "")
                            if name:
                                entity_names.append(name)
                                if typ:
                                    entity_types[name] = typ
                        elif isinstance(ent, str):
                            entity_names.append(ent)

                return AnalyzedQuery(
                    domain=response.get("domain", "general"),
                    intent=response.get("intent", "") or "general",
                    entities=entity_names,
                    entity_types=entity_types,
                    sub_questions=response.get("sub_questions", []),
                    reasoning=response.get("reasoning", ""),
                )
            except Exception as e:
                logger.warning(f"[query_analyzer] parse failed: {e}")

        return self._fallback(question)

    def _fallback(self, question: str) -> AnalyzedQuery:
        import re
        # 从问题中提取关键词作为实体兜底
        tokens = re.split(r'[的，。,．？?！!、\s]+', question)
        keywords = [t.strip() for t in tokens if len(t.strip()) >= 2]

        return AnalyzedQuery(
            domain="workforce",
            intent="general",
            entities=keywords,
            entity_types={k: "concept" for k in keywords},
            required_sources=["entity", "graph_relation", "document_summary", "database_summary"],
        )

