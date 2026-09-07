"""文档源业务逻辑层

封装从概要文件提取实体和关系的完整管道：
读文件 → 分段 → LLM 并发提取 → 去重 → 持久化
"""

import os
import re
import json
from typing import Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from system.logger import logger


def iter_segments(node, max_chunk: int = 20000):
    """从 PageIndex 树节点逐个 yield (title, text) 元组，超长段按句子边界切分"""
    if isinstance(node, dict):
        title = node.get("title", "")
        if "text" in node and node["text"]:
            seg = node["text"].strip()
            if seg:
                if len(seg) <= max_chunk:
                    yield (title, seg)
                else:
                    for i, part in enumerate(split_text(seg, max_chunk)):
                        yield (f"{title}(切{i+1})", part)
        for key, val in node.items():
            if isinstance(val, (dict, list)):
                yield from iter_segments(val, max_chunk)
    elif isinstance(node, list):
        for item in node:
            yield from iter_segments(item, max_chunk)


def split_text(text: str, max_chunk: int):
    """按句子边界切分长文本，每块不超过 max_chunk 字符"""
    sentences = re.split(r'(?<=[。！？\n])', text)
    current = ""
    for s in sentences:
        if not s.strip():
            continue
        if len(current) + len(s) <= max_chunk:
            current += s
        else:
            if current:
                yield current
            if len(s) > max_chunk:
                for i in range(0, len(s), max_chunk):
                    yield s[i:i + max_chunk]
            else:
                current = s
    if current:
        yield current


def merge_segments_iter(segments, max_chunk: int = 20000, min_size: int = 1000):
    """将不足 min_size 的段合并为大块并逐个 yield，合并后总长度不超过 max_chunk"""
    buffer = ""
    buffer_titles = []
    chunk_index = 0

    for title, seg in segments:
        if len(seg) >= min_size:
            if buffer:
                if len(buffer) + len(seg) <= max_chunk:
                    chunk_index += 1
                    titles = buffer_titles + [title]
                    logger.info(f"合并块 {chunk_index}: {' + '.join(titles)} (总长: {len(buffer + seg)})")
                    yield buffer + seg
                else:
                    chunk_index += 1
                    if buffer_titles:
                        logger.info(f"合并块 {chunk_index}: {' + '.join(buffer_titles)} (总长: {len(buffer)})")
                    else:
                        logger.info(f"合并块 {chunk_index}: (总长: {len(buffer)})")
                    yield buffer
                    chunk_index += 1
                    logger.info(f"合并块 {chunk_index}: {title} (总长: {len(seg)})")
                    yield seg
                buffer = ""
                buffer_titles = []
            else:
                chunk_index += 1
                logger.info(f"合并块 {chunk_index}: {title} (总长: {len(seg)})")
                yield seg
        else:
            if len(buffer) + len(seg) > max_chunk:
                chunk_index += 1
                if buffer_titles:
                    logger.info(f"合并块 {chunk_index}: {' + '.join(buffer_titles)} (总长: {len(buffer)})")
                else:
                    logger.info(f"合并块 {chunk_index}: (总长: {len(buffer)})")
                yield buffer
                buffer = seg
                buffer_titles = [title] if title else []
            else:
                buffer += seg
                if title and (not buffer_titles or buffer_titles[-1] != title):
                    buffer_titles.append(title)
    if buffer:
        chunk_index += 1
        if buffer_titles:
            logger.info(f"合并块 {chunk_index}: {' + '.join(buffer_titles)} (总长: {len(buffer)})")
        else:
            logger.info(f"合并块 {chunk_index}: (总长: {len(buffer)})")
        yield buffer


class SourceService:
    """文档源业务逻辑层"""

    def __init__(self, model_config: dict):
        self.model_config = model_config

    def extract_from_summary(
        self,
        summary_path: str,
        datasource: str,
        parallelism: int = 8,
    ) -> Dict[str, Any]:
        """从概要文件提取实体和关系。

        流程：读文件 → 分段 → LLM 并发提取 → 去重 → 持久化
        """
        from entity_extraction.llm_entity_enhancer import LLMEntityEnhancer
        from utils.data_store import EntityDataStore

        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)

        enhancer = LLMEntityEnhancer(model_config=self.model_config)

        # 流式分段、合并、提交 LLM 调用
        structure = summary.get("structure", [])
        segments = iter_segments(structure)
        chunks = merge_segments_iter(segments)

        all_entities = []
        all_relationships = []
        lock = Lock()

        def extract_one(idx: int, chunk: str):
            logger.info(f"提取第 {idx+1} 块，长度: {len(chunk)}")
            result = enhancer.extract_entities_and_relationships(chunk)
            return result.get("entities", []), result.get("relationships", [])

        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            futures = {}
            chunk_count = 0
            for i, chunk in enumerate(chunks):
                chunk_count += 1
                logger.info(f"提交第 {chunk_count} 块到LLM")
                future = executor.submit(extract_one, i, chunk)
                futures[future] = i

            logger.info(f"共 {chunk_count} 个文本块，开始提取")

            if chunk_count == 0:
                raise ValueError("概要中没有可提取的文本内容")

            for future in as_completed(futures):
                ents, rels = future.result()
                with lock:
                    all_entities.extend(ents)
                    all_relationships.extend(rels)

        # 全局去重
        seen_entity = set()
        entities = []
        for e in all_entities:
            key = f"{e.get('n', '')}_{e.get('t', '')}"
            if key not in seen_entity:
                seen_entity.add(key)
                e["datasource"] = datasource
                entities.append(e)

        seen_rel = set()
        relationships = []
        for r in all_relationships:
            key = f"{r.get('s', '')}_{r.get('p', '')}_{r.get('o', '')}"
            if key not in seen_rel:
                seen_rel.add(key)
                relationships.append(r)

        # 保存到知识库和图谱
        entity_count, rel_count = EntityDataStore.save_all(
            entities, relationships, datasource=datasource
        )

        logger.info(f"实体关系提取完成: entities={entity_count}, relationships={rel_count}")
        return {
            "entity_count": entity_count,
            "relationship_count": rel_count,
            "entities": entities,
            "relationships": relationships,
        }
