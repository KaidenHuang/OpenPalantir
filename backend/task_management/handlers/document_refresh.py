from typing import Callable, Dict

from system.logger import logger

from .base import TaskHandler


class DocumentRefreshHandler(TaskHandler):
    """文档内容失效传播：重跑摘要 → 回收旧图谱产出 → 重新抽取 → 刷新 Wiki"""

    TASK_TYPE = "document_refresh"
    REQUIRED_KEYS = ("source_id", "file_path")
    OPTIONAL_DEFAULTS = {"force": False, "domain": "general", "parallelism": 8}

    def execute(self, task, progress_callback: Callable[[int], None]) -> Dict:
        from pipeline import refresh

        self.validate_payload(task.payload)
        source_id = task.payload.get("source_id")
        file_path = task.payload.get("file_path")

        logger.info(f"[DocumentRefreshHandler] 入参: source_id={source_id}, file={file_path}")
        progress_callback(10)

        result = refresh.refresh_document(
            source_id,
            file_path,
            force=self.payload_value(task, "force"),
            domain=self.payload_value(task, "domain"),
            parallelism=self.payload_value(task, "parallelism"),
        )

        progress_callback(100)
        task.result = result
        logger.info(f"[DocumentRefreshHandler] 完成: {result.get('status')} {file_path}")
        return result
