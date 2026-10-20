"""文档批量实体抽取任务 —— 摘要在先的文件逐个抽取：代际佐证 + 零实体守卫 + 文件间并发"""
import os
from threading import Lock
from typing import Callable, Dict

from system.logger import logger

from .base import CONCURRENCY_DEFAULT, TaskHandler, run_files_concurrently


class DocumentBatchExtractHandler(TaskHandler):
    """批量按摘要提取实体关系（files 支持目录展开；缺摘要记 failure 继续）

    与单文件 /extract 语义一致：不回收旧代产出（MERGE 幂等，佐证累积），
    需要代际刷新走 document_refresh。

    批后刷新 Wiki 但带省钱闸：本批一个实体都没新增就跳过 —— 刷 Wiki 要扫全图
    实体，为一次空产出付这笔成本不值。跳过时结果里 `wiki_pages` 为 null，
    界面据此区分「没刷」与「刷了但没变化」。刷新失败仅记账，不影响已写图谱。
    """

    TASK_TYPE = "document_batch_extract"
    REQUIRED_KEYS = ("source_id",)
    OPTIONAL_DEFAULTS = {
        "files": None,
        "domain": "general",
        "parallelism": 8,
        "concurrency": CONCURRENCY_DEFAULT,
    }

    def execute(self, task, progress_callback: Callable[[int], None]) -> Dict:
        from config.database import SessionLocal
        from entity_extraction.document.service import (
            DocumentExtractionService,
            guard_llm_available,
        )
        from model_management.model_service import ModelService
        from source_registry.document.scanner import collect_for_source
        from summary_generation.document import store as summary_generator

        self.validate_payload(task.payload)
        source_id = task.payload.get("source_id")
        domain = self.payload_value(task, "domain")
        parallelism = self.payload_value(task, "parallelism")
        concurrency = self.payload_value(task, "concurrency")

        # 模型快照一次：全批共用（extract_from_summary 内部无共享可变状态）
        db = SessionLocal()
        try:
            model_config = ModelService.get_available_model(db)
        finally:
            db.close()
        if not model_config:
            raise RuntimeError("没有可用的模型，无法提取实体关系")

        _, files, entry_failures = collect_for_source(source_id, task.payload.get("files"))
        if not files:
            raise ValueError("没有可处理的文件（清单为空，或条目扩展名均不支持）")
        total = len(files)
        logger.info(f"[DocumentBatchExtractHandler] source={source_id}, files={total}, "
                    f"domain={domain}, parallelism={parallelism}, concurrency={concurrency}")
        progress_callback(5)

        service = DocumentExtractionService(model_config)

        counts = {"entities": 0, "relationships": 0}
        counts_lock = Lock()

        def worker(rel: str):
            summary_abs = summary_generator.summary_path(source_id, rel.replace("\\", "/"))
            if not os.path.isfile(summary_abs):
                raise ValueError("摘要不存在，请先生成概要")
            datasource = summary_generator.datasource_for(source_id, rel)
            evidence_hash = summary_generator.stored_content_hash(summary_abs)
            result = service.extract_from_summary(
                summary_path=summary_abs,
                datasource=datasource,
                parallelism=parallelism,
                domain=domain,
                evidence_hash=evidence_hash or None,
            )
            # 零实体守卫看的是"批次是否全灭"，不是结果数：合法 0 实体（纯数据表、
            # 全是属性列）不该让任务失败，全批调用失败才是 LLM 不可用。
            guard_llm_available(result, "抽取")
            entity_count = (result or {}).get("entity_count", 0)
            with counts_lock:
                counts["entities"] += entity_count
                counts["relationships"] += (result or {}).get("relationship_count", 0)
            return result

        def on_processed(done: int, _total: int) -> None:
            progress_callback(int(5 + done * 95 / total))

        stats = run_files_concurrently(task, files, concurrency, worker, on_processed)
        failures = entry_failures + stats["failures"]

        wiki_pages = None
        if counts["entities"] > 0:
            try:
                wiki_pages = _refresh_wiki()
            except Exception as e:
                # 批量抽取已成功写图谱；Wiki 刷新失败仅记账不回滚
                logger.warning(f"[DocumentBatchExtractHandler] 批量后 Wiki 刷新失败（不影响图谱）: {e}")
        else:
            logger.info("[DocumentBatchExtractHandler] 本批无新增实体，跳过批后 Wiki 刷新")

        result = {
            "status": "success",
            "source_id": source_id,
            "domain": domain,
            "total": total,
            "succeeded": stats["succeeded"],
            "skipped": stats["skipped"],
            "failed": len(failures),
            "failures": failures,
            "entity_count": counts["entities"],
            "relationship_count": counts["relationships"],
            "wiki_pages": wiki_pages,
        }
        logger.info(f"[DocumentBatchExtractHandler] 完成: 实体 {result['entity_count']}, "
                    f"关系 {result['relationship_count']}，失败 {result['failed']}")
        return result


def _refresh_wiki() -> Dict:
    """批量抽取后的 Wiki 就地刷新（主题页/实体页按指纹重算 + 孤儿页清理）"""
    from wiki_generation.service import wiki_service

    topic_pages = wiki_service.refresh_topics()
    entity_pages = wiki_service.generate_entity_pages()
    pruned = wiki_service.prune_orphans()
    return {"topic_pages": len(topic_pages), "entity_pages": len(entity_pages), "pruned_pages": pruned}
