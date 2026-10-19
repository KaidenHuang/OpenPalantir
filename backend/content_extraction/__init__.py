"""② 内容提取 —— 文档/数据库分侧实现（纯解析，无 LLM）

document/  各格式文档 → 统一 ExtractedDocument（章节树 + 页码锚点）
database/  连接配置 → DatabaseSchema（表/字段/主外键/视图）

新增文档格式（图片、音频、视频）时在 document/converters/ 注册表登记即可。
"""
from content_extraction.document import ExtractedDocument, Section, extract_content
from content_extraction.database.schema_reader import extract_schema_for_connection


__all__ = [
    "extract_content",
    "extract_schema_for_connection",
    "ExtractedDocument",
    "Section",
]
