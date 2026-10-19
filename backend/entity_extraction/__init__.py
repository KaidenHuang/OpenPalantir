"""④ 实体抽取 —— 文档/数据库分侧实现，把「已提取内容」变成图谱

document/  摘要批次 → LLM 实体/关系/实体属性 → 去重 → 落库
database/  关系型行 → 行实体 + 主外键/属性表关系 → 落库

两侧共用 knowledge_graph 的写入缝（谓词归一化、ID 计算、来源佐证都在那里）。
"""
from entity_extraction.document.chunker import dedupe_extraction, iter_segments, merge_segments_iter
from entity_extraction.document.service import DocumentExtractionService

__all__ = [
    "DocumentExtractionService",
    "dedupe_extraction",
    "iter_segments",
    "merge_segments_iter",
]
