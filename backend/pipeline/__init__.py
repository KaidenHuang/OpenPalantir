"""跨阶段调度薄层 —— 失效传播与增量监听

refresh  文档内容失效传播（先摘要→抽取→旧代回收→Wiki），完结于 stage ③⑤ 的接口
watcher  轮询内容指纹自动派发刷新任务（与 CDC 对称：CDC 管数据库行级增量）
"""
from pipeline.refresh import recycle_document, refresh_document, remove_document, scan_stale, stale_reason
from pipeline.watcher import document_watcher

__all__ = [
    "recycle_document",
    "refresh_document",
    "remove_document",
    "scan_stale",
    "stale_reason",
    "document_watcher",
]
