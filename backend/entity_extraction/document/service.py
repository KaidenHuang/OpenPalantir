"""④ 实体抽取（文档侧）—— 摘要 → 实体/关系 → 图谱

正文类文档的数据来源是阶段③落盘的摘要 JSON：摘要里已经是切好的章节正文，
抽取只按 token 预算合并批次并发调用 LLM，不重读源文件。

摘要里声明 `kind=table` 的文档（② 的节级 kind 聚合而来，不是按文件扩展名反推）是这条
契约的显式例外，走 `table_service.import_tables`：
全表行值是数据不是文章，塞进摘要 JSON 会让摘要变成几十 MB 的数据副本，所以④ 重读源文件
取真实行值，按③ 的列标注纯规则装配列实体，零 LLM 调用。例外换来的约束（必须走
`iter_table_rows` 取行、落库前校验源文件指纹）都在那个模块里，不在这层。
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional

from content_extraction.document.models import KIND_TABLE
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
        evidence_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """从摘要文件提取实体和关系。

        流程：读文件 → 表格分支/正文分支 → LLM 并发提取 → 去重（含属性合并）→ 持久化
        domain 决定注入 prompt 的实体/关系/属性本体词表。
        evidence_hash 透传 content_hash 代际标记（佐证条目落 URI@hash）。
        """
        from entity_extraction.document.extractor import LLMEntityEnhancer
        from knowledge_graph.entity_data_store import EntityDataStore

        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)

        if summary.get("kind") == KIND_TABLE:
            from entity_extraction.document.table_service import import_tables

            return import_tables(summary, datasource, domain=domain,
                                 evidence_hash=evidence_hash)

        enhancer = LLMEntityEnhancer(model_config=self.model_config)

        structure = summary.get("structure", [])
        segments = iter_segments(structure)
        chunks = merge_segments_iter(segments)

        all_entities = []
        all_relationships = []
        batch_failed = 0

        def extract_one(idx: int, chunk: str):
            logger.info(f"提取第 {idx+1} 块，长度: {len(chunk)}")
            result = enhancer.extract_entities_and_relationships(chunk, domain=domain)
            return (result.get("entities", []), result.get("relationships", []),
                    bool(result.get("batch_failed")))

        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            futures = {}
            for i, chunk in enumerate(chunks):
                logger.info(f"提交第 {i + 1} 块到LLM")
                futures[executor.submit(extract_one, i, chunk)] = i
            chunk_count = len(futures)

            logger.info(f"共 {chunk_count} 个文本块，开始提取")

            if chunk_count == 0:
                raise ValueError("概要中没有可提取的文本内容")

            for future in as_completed(futures):
                ents, rels, failed = future.result()
                all_entities.extend(ents)
                all_relationships.extend(rels)
                batch_failed += int(failed)

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
            "batch_total": chunk_count,
            "batch_failed": batch_failed,
            "entities": entities,
            "relationships": relationships,
        }


def guard_llm_available(result: Dict[str, Any], action: str) -> Dict[str, Any]:
    """抽取结果守卫：只有「批次全灭」才判 LLM 不可用

    旧判据是 entity_count == 0，但它把两种情况混在一起：LLM 每次调用都失败（必须报警），
    和这份文档合法地没有可抽实体（纯序号列的表、全是属性列的表、③ 降级无标注）。
    后者按失败处理会让刷新永久失败，而现有顺序下旧图谱产出不会被回收，
    用户看到的是"抽取失败"，实际一切正常 —— 所以守卫看的是调用是否全灭，不是结果数。
    """
    result = result or {}
    total = int(result.get("batch_total") or 0)
    failed = int(result.get("batch_failed") or 0)
    if total and failed >= total:
        raise RuntimeError(
            f"{action}的 {total} 个批次全部调用失败（大概率 LLM 不可用）；"
            "旧图谱产出未回收，请检查模型配置后重跑"
        )
    if not result.get("entity_count"):
        # total 为 0 时打「0/0 批次调用成功」等于没说话：短文与表格装配分支本来就不发调用
        if total:
            logger.info(f"[entity_extraction] {action}得到 0 个实体，但 {total - failed}/{total} "
                        "批次调用成功，判为合法空产出")
        else:
            logger.info(f"[entity_extraction] {action}得到 0 个实体，本次没有 LLM 调用"
                        "（短文或表格装配分支），判为合法空产出")
    return result
