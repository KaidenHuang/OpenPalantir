"""① 注册数据源 —— 文档源与数据库源的统一注册入口

document/  文档源（本地路径/S3）注册、浏览、生命周期
database/  数据库源连接注册、测试、生命周期

本组件只负责「源的存在与可达」，不涉及内容提取与解析。
"""
from source_registry.document.registry import document_source_registry
from source_registry.database.registry import database_source_registry

__all__ = [
    "document_source_registry",
    "database_source_registry",
]
