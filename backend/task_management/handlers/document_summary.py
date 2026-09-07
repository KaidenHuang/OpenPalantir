import json
import os
from typing import Any, Callable, Dict

from system.logger import logger

from .base import TaskHandler


class DocumentSummaryHandler(TaskHandler):
    """执行文档概要生成任务"""

    def execute(self, task, progress_callback: Callable[[int], None]) -> Dict:
        logger.info(f"[DocumentSummaryHandler] 入参: task_id={task.task_id}")
        from pageindex import (
            generate_pageindex_pdf,
            generate_pageindex_md,
            generate_pageindex_txt,
            generate_pageindex_docx,
        )

        try:
            source_id = task.payload.get("source_id")
            file_path = task.payload.get("file_path")
            full_path = task.payload.get("full_path")

            if not all([source_id, file_path, full_path]):
                raise ValueError("缺少必要参数: source_id, file_path, full_path")

            ext = os.path.splitext(full_path)[1].lower()
            logger.info(
                f"开始生成文档概要: source_id={source_id}, file={file_path}, ext={ext}"
            )

            if ext == ".pdf":
                result = generate_pageindex_pdf(full_path)
            elif ext == ".md":
                result = generate_pageindex_md(full_path)
            elif ext == ".txt":
                result = generate_pageindex_txt(full_path)
            elif ext == ".docx":
                result = generate_pageindex_docx(full_path)
            else:
                raise ValueError(f"不支持的文件类型: {ext}")

            progress_callback(70)

            summary_rel_path = file_path + ".json"
            summary_abs_path = os.path.join(
                "data", "summaries", "DOC", source_id, summary_rel_path
            )
            os.makedirs(os.path.dirname(summary_abs_path), exist_ok=True)
            with open(summary_abs_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            logger.info(f"文档概要已保存: {summary_abs_path}")

            progress_callback(100)

            task.result = {
                "status": "success",
                "file": file_path,
                "summary_path": summary_rel_path,
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