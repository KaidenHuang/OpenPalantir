"""④ 实体抽取（文档侧）—— 摘要批次 → LLM 实体/关系/属性 → 图谱

数据来源是阶段③落盘的摘要 JSON（原文批次），不重读源文件：
摘要里已经是切好的章节正文，抽取只按 token 预算合并批次并发调用 LLM。
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict

from entity_extraction.document.chunker import (
    dedupe_extraction,
    iter_segments,
    merge_segments_iter,
)
from system.logger import logger


class DocumentExtractionService:
    """文档 → 实体/关系/实体属性（LLM 并发抽取 + 去重 + 落库）"""

    def __init__(self, model_config: dict):
        self.model_config = model_config

    def extract_from_summary(
        self,
        summary_path: str,
        datasource: str,
        parallelism: int = 8,
        domain: str = "general",
        evidence_hash: str = None,
    ) -> Dict[str, Any]:
        """从摘要文件提取实体和关系。

        流程：读文件 → 分段 → LLM 并发提取 → 去重（含属性合并）→ 持久化
        domain 决定注入 prompt 的实体/关系/属性本体词表。
        evidence_hash 透传 content_hash 代际标记（佐证条目落 URI@hash）。
        """
        from entity_extraction.document.extractor import LLMEntityEnhancer
        from knowledge_graph.entity_data_store import EntityDataStore

        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)

        enhancer = LLMEntityEnhancer(model_config=self.model_config)

        structure = summary.get("structure", [])
        segments = iter_segments(structure)
        chunks = merge_segments_iter(segments)

        all_entities = []
        all_relationships = []

        def extract_one(idx: int, chunk: str):
            logger.info(f"提取第 {idx+1} 块，长度: {len(chunk)}")
            result = enhancer.extract_entities_and_relationships(chunk, domain=domain)
            return result.get("entities", []), result.get("relationships", [])

        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            futures = {}
            chunk_count = 0
            for i, chunk in enumerate(chunks):
                chunk_count += 1
                logger.info(f"提交第 {chunk_count} 块到LLM")
                futures[executor.submit(extract_one, i, chunk)] = i

            logger.info(f"共 {chunk_count} 个文本块，开始提取")

            if chunk_count == 0:
                raise ValueError("概要中没有可提取的文本内容")

            for future in as_completed(futures):
                ents, rels = future.result()
                all_entities.extend(ents)
                all_relationships.extend(rels)

        entities, relationships = dedupe_extraction(all_entities, all_relationships)
        for e in entities:
            e["datasource"] = datasource

        entity_count, rel_count = EntityDataStore.save_all(
            entities, relationships, datasource=datasource,
            evidence_hash=evidence_hash,
        )

        logger.info(f"实体关系提取完成: entities={entity_count}, relationships={rel_count}")
        return {
            "entity_count": entity_count,
            "relationship_count": rel_count,
            "entities": entities,
            "relationships": relationships,
        }
