from typing import Callable, Dict

from system.logger import logger

from .base import TaskHandler


class DocumentRefreshHandler(TaskHandler):
    """文档内容失效传播：重跑摘要 → 回收旧图谱产出 → 重新抽取 → 刷新 Wiki"""

    def execute(self, task, progress_callback: Callable[[int], None]) -> Dict:
        from source_management import refresh_service

        source_id = task.payload.get("source_id")
        file_path = task.payload.get("file_path")
        if not source_id or not file_path:
            raise ValueError("缺少必要参数: source_id, file_path")

        logger.info(f"[DocumentRefreshHandler] 入参: source_id={source_id}, file={file_path}")
        progress_callback(10)

        result = refresh_service.refresh_document(
            source_id,
            file_path,
            force=bool(task.payload.get("force", False)),
            domain=task.payload.get("domain", "general"),
            parallelism=int(task.payload.get("parallelism", 8)),
        )

        progress_callback(100)
        task.result = result
        logger.info(f"[DocumentRefreshHandler] 完成: {result.get('status')} {file_path}")
        return result
