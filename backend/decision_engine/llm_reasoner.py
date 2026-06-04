import json
import os

from model_management.model_client import get_model_client
from system.logger import logger
from decision_engine.contracts import DecisionAnswer, EvidenceItem, StructuredContext, WorkOrder

FALLBACK_ANSWER = DecisionAnswer(
    summary="已完成基于证据的初步分析，建议进一步收集数据后制定详细方案。",
    situation_analysis="当前数据不足以进行深入分析，建议先完成数据采集和整理。",
    recommendation="建议优先完善数据基础，再进行系统化决策分析。",
    work_orders=[
        WorkOrder(title="数据完整性检查", priority="P1", owner_role="数据分析师",
                  steps=["确认数据源连接", "检查数据时效性", "补充缺失字段"],
                  acceptance_criteria=["数据完整率达到90%以上"]),
    ],
)

MAX_PROMPT_CHARS = 20000


class LLMReasoner:
    _prompt: str = ""

    @classmethod
    def _load_prompt(cls) -> str:
        if not cls._prompt:
            path = os.path.join(os.path.dirname(__file__), "prompts", "prompt_decision_reason.md")
            with open(path, "r", encoding="utf-8") as f:
                cls._prompt = f.read()
        return cls._prompt

    @staticmethod
    def _build_json_obj(e: EvidenceItem) -> dict:
        """根据 source_type 将 EvidenceItem 转为 JSON dict"""
        if e.source_type == "entity":
            return {"name": e.source_name, "type": e.payload.get("type", ""),
                    "description": e.summary}
        if e.source_type == "graph_relation":
            return {"source": e.payload.get("source", ""),
                    "predicate": e.payload.get("predicate", ""),
                    "target": e.payload.get("target", ""),
                    "description": e.summary}
        # database_summary / document_summary — payload 字段已对齐原格式
        return e.payload

    @staticmethod
    def _fmt_json_section(items, header):
        """将 EvidenceItem 列表序列化为 JSON 数组"""
        if not items:
            return f"{header}\n\n（无相关数据）"
        objs = [LLMReasoner._build_json_obj(e) for e in items]
        return f"{header}\n\n{json.dumps(objs, ensure_ascii=False)}"

    @staticmethod
    def _truncate_fit(items, header, budget):
        """在预算内尽可能多地放入条目（按相关性降序），适配 JSON 格式"""
        no_data = f"{header}\n\n（无相关数据）"
        if not items:
            return no_data if len(no_data) <= budget else ""
        if budget <= 0:
            return ""
        sorted_items = sorted(items, key=lambda e: e.relevance_score, reverse=True)
        included = []
        for e in sorted_items:
            obj = LLMReasoner._build_json_obj(e)
            candidate = json.dumps(included + [obj], ensure_ascii=False)
            if len(f"{header}\n\n{candidate}") <= budget:
                included.append(obj)
            else:
                break
        if included:
            return f"{header}\n\n{json.dumps(included, ensure_ascii=False)}"
        return no_data if len(no_data) <= budget else ""

    def reason(self, context: StructuredContext) -> DecisionAnswer:
        model_client = get_model_client()
        if not model_client:
            logger.warning("[llm_reasoner] LLM unavailable, using fallback")
            return FALLBACK_ANSWER

        entity_sec = self._fmt_json_section(context.entity_context, "### 实体信息")
        graph_sec = self._fmt_json_section(context.graph_context, "### 实体关联关系")
        db_sec = self._fmt_json_section(context.database_context, "### 数据库业务概要")
        doc_sec = self._fmt_json_section(context.document_context, "### 相关文档摘要")

        sub_qs = "（无补充子问题）"
        if context.sub_questions:
            sub_qs = "\n".join(f"- {q}" for q in context.sub_questions)

        template = self._load_prompt()
        _, footer_raw = template.split("## 分析要求", 1)
        footer = ("\n## 分析要求" + footer_raw).format(question=context.question)

        sub_qs_section = f"\n\n### 补充子问题\n\n{sub_qs}"

        header = f"# 智能决策推理任务\n\n你是一个专业的 {context.domain} 决策分析师。请基于以下证据给出决策建议。\n\n## 输入数据\n"
        body = header + "\n" + entity_sec + "\n\n" + graph_sec
        remaining = MAX_PROMPT_CHARS - len(body) - len(sub_qs_section) - len(footer)

        if remaining > 0 and context.database_context:
            db_block = "\n\n" + db_sec
            if len(db_block) <= remaining:
                body += db_block
                remaining -= len(db_block)
            else:
                truncated = self._truncate_fit(context.database_context, "### 数据库业务概要", remaining - 2)
                if truncated:
                    body += "\n\n" + truncated
                    remaining = MAX_PROMPT_CHARS - len(body) - len(sub_qs_section) - len(footer)

        if remaining > 0 and context.document_context:
            doc_block = "\n\n" + doc_sec
            if len(doc_block) <= remaining:
                body += doc_block
            else:
                truncated = self._truncate_fit(context.document_context, "### 相关文档摘要", remaining - 2)
                if truncated:
                    body += "\n\n" + truncated

        body += sub_qs_section + footer
        prompt = body

        logger.debug(f"[llm_reasoner] 最终提示词 ({len(prompt)} chars):\n{prompt}")

        response = model_client.call_json(prompt=prompt,
                                          system_prompt=f"你是严谨的{context.domain}决策助手。")
        if not response:
            logger.warning("[llm_reasoner] empty response, using fallback")
            return FALLBACK_ANSWER

        try:
            work_orders_raw = response.get("work_orders", [])
            work_orders = []
            for wo in work_orders_raw:
                if isinstance(wo, dict):
                    work_orders.append(WorkOrder(**wo))
                else:
                    logger.warning(f"[llm_reasoner] skip invalid work_order: {type(wo)}")

            rec = response.get("recommendation", "")
            if isinstance(rec, dict):
                rec = json.dumps(rec, ensure_ascii=False)

            situation = response.get("situation_analysis", "")
            if isinstance(situation, dict):
                situation = json.dumps(situation, ensure_ascii=False)

            return DecisionAnswer(
                summary=str(response.get("summary", situation))[:500],
                situation_analysis=situation,
                key_issues=response.get("key_issues", []),
                options=response.get("options", []),
                recommendation=rec,
                work_orders=work_orders,
            )
        except Exception as e:
            logger.warning(f"[llm_reasoner] parse failed: {e}")
            return FALLBACK_ANSWER
