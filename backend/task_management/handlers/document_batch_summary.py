"""文档批量摘要任务 —— 单源多文件一次生成：全源扫描/清单 + 目录展开 + 文件间并发"""
import os
from typing import Callable, Dict

from system.logger import logger

from utils.path_guard import safe_join

from .base import CONCURRENCY_DEFAULT, TaskHandler, run_files_concurrently


class DocumentBatchSummaryHandler(TaskHandler):
    """批量生成文档摘要（单失败不终止整批，模型不可用整批失败）

    payload 契约见 OPTIONAL_DEFAULTS：files 为 None 时按全源递归枚举，
    条目可以是目录（后端展开）；force=True 时指纹一致的摘要也重跑。
    """

    TASK_TYPE = "document_batch_summary"
    REQUIRED_KEYS = ("source_id",)
    OPTIONAL_DEFAULTS = {"files": None, "force": False, "concurrency": CONCURRENCY_DEFAULT}

    def execute(self, task, progress_callback: Callable[[int], None]) -> Dict:
        from source_registry.document.scanner import collect_for_source
        from summary_generation.document import store as summary_generator
        from summary_generation.document.llm import get_model_config

        self.validate_payload(task.payload)
        source_id = task.payload.get("source_id")
        force = bool(self.payload_value(task, "force"))
        concurrency = self.payload_value(task, "concurrency")

        # 模型检查前置：批量任务在第一分钟内就应该失败，而不是逐文件收集一堆同因失败
        if not get_model_config():
            raise RuntimeError("没有可用的模型，无法生成文档摘要")

        base_path, files, entry_failures = collect_for_source(source_id, task.payload.get("files"))
        if not files:
            raise ValueError("没有可处理的文件（清单为空，或条目扩展名均不支持）")
        total = len(files)
        logger.info(f"[DocumentBatchSummaryHandler] source={source_id}, "
                    f"files={total}, force={force}, concurrency={concurrency}")
        progress_callback(5)

        def worker(rel: str):
            full_path = safe_join(base_path, rel.replace("\\", "/"))
            if not os.path.isfile(full_path):
                raise ValueError("文件不存在")
            if not force and _summary_fresh(source_id, rel, full_path):
                return False  # 幂等跳过：摘要存在且 content_hash 与源一致
            result = summary_generator.generate(full_path, source_id=source_id,
                                                file_path=rel)
            summary_generator.save(source_id, rel, result)
            return True

        def on_processed(done: int, _total: int) -> None:
            progress_callback(int(5 + done * 95 / total))

        stats = run_files_concurrently(task, files, concurrency, worker, on_processed)
        failures = entry_failures + stats["failures"]

        result = {
            "status": "success",
            "source_id": source_id,
            "total": total,
            "succeeded": stats["succeeded"],
            "skipped": stats["skipped"],
            "failed": len(failures),
            "failures": failures,
        }
        logger.info(f"[DocumentBatchSummaryHandler] 完成: 成功 {result['succeeded']}, "
                    f"跳过 {result['skipped']}, 失败 {result['failed']}")
        return result


def _summary_fresh(source_id: str, file_path: str, full_path: str) -> bool:
    """跳过判定：摘要已存在且其中 content_hash 与当前源文件指纹一致"""
    from summary_generation.document import store as summary_generator

    stored = summary_generator.stored_content_hash(summary_generator.summary_path(source_id, file_path))
    if not stored:
        return False
    return summary_generator.file_content_hash(full_path) == stored
