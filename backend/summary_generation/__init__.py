"""③ 摘要生成 —— 文档/数据库分侧实现，消费来自阶段②的提取产物

document/  ExtractedDocument → 摘要树（自底向上：叶子与父节点都 summary + 自身正文 text，父节点另带 nodes）+ 落盘 store
database/  Schema 标注（annotator）+ 库表概要组装（build）+ 落盘 store
"""
from summary_generation.document import store as document_store
from summary_generation.database import store as database_store

__all__ = ["document_store", "database_store"]
