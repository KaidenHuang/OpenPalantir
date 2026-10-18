import os
from typing import Callable, Dict

from system.logger import logger

from .base import TaskHandler


class DocumentSummaryHandler(TaskHandler):
    """执行文档概要生成任务"""

    def execute(self, task, progress_callback: Callable[[int], None]) -> Dict:
        logger.info(f"[DocumentSummaryHandler] 入参: task_id={task.task_id}")
        from document_processing import summary_generator

        source_id = task.payload.get("source_id")
        file_path = task.payload.get("file_path")
        full_path = task.payload.get("full_path")

        if not all([source_id, file_path, full_path]):
            raise ValueError("缺少必要参数: source_id, file_path, full_path")

        ext = os.path.splitext(full_path)[1].lower()
        logger.info(
            f"开始生成文档概要: source_id={source_id}, file={file_path}, ext={ext}"
        )

        try:
            result = summary_generator.generate(full_path)
            progress_callback(80)

            summary_generator.save(source_id, file_path, result)
            progress_callback(100)

            task.result = {
                "status": "success",
                "file": file_path,
                "summary_path": file_path + ".json",
                "content_hash": result.get("content_hash", ""),
                "doc_name": result.get("doc_name", ""),
                "doc_description": result.get("doc_description", ""),
            }
            logger.info(f"[DocumentSummaryHandler] 完成: file={file_path}")
            return task.result

        except RuntimeError as e:
            logger.error(f"文档概要生成失败(模型不可用): {e}")
            raise
        except Exception as e:
            logger.error(f"文档概要生成任务异常: {e}")
            raise
