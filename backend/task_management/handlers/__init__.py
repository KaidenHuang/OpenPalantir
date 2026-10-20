"""任务处理器注册表 — task_type → handler 契约的单一映射来源

每个 handler 类用 ``TASK_TYPE`` 声明类型常量并声明 payload 契约
（见 handlers/base.py），创建点引用常量而非裸字符串。
"""
from .base import TaskHandler
from .schema_analyze import SchemaAnalyzeHandler
from .schema_import import SchemaImportHandler
from .cdc_start import CdcStartHandler
from .document_summary import DocumentSummaryHandler
from .document_refresh import DocumentRefreshHandler
from .document_batch_summary import DocumentBatchSummaryHandler
from .document_batch_extract import DocumentBatchExtractHandler
from .wiki_generate import WikiGenerateHandler

__all__ = [
    "TaskHandler",
    "HANDLERS",
    "SchemaAnalyzeHandler",
    "SchemaImportHandler",
    "CdcStartHandler",
    "DocumentSummaryHandler",
    "DocumentRefreshHandler",
    "DocumentBatchSummaryHandler",
    "DocumentBatchExtractHandler",
    "WikiGenerateHandler",
]

# task_type → handler 契约（TASK_TYPE → 实现类），create_task 与调度共用同一份
HANDLERS: dict = {
    h.TASK_TYPE: h for h in (
        SchemaAnalyzeHandler, SchemaImportHandler, CdcStartHandler,
        DocumentSummaryHandler, DocumentRefreshHandler,
        DocumentBatchSummaryHandler, DocumentBatchExtractHandler, WikiGenerateHandler,
    )
}
