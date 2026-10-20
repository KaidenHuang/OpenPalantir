"""
文档批量任务测试

覆盖：可处理文件枚举（目录展开/扩展名过滤/清单级失败）、并发骨架
（失败隔离/幂等跳过/停止取消）、批量摘要与批量抽取 handler 的执行路径
（模型前置检查、空清单拒绝、成败统计口径）。不依赖 LLM / Neo4j。
"""
import json
import os
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

import pytest

from source_registry.document import scanner
from task_management.handlers.base import TaskStopped, run_files_concurrently
from task_management.handlers.document_batch_summary import DocumentBatchSummaryHandler
from task_management.handlers.document_batch_extract import DocumentBatchExtractHandler


@pytest.fixture()
def src(tmp_path):
    """临时文档源：a.md / b.txt / c.md / sub/d.md，sub 里还有个不支持的 e.xyz"""
    src = tmp_path / "docs"
    src.mkdir()
    (src / "a.md").write_text("A", encoding="utf-8")
    (src / "b.txt").write_text("B", encoding="utf-8")
    (src / "c.md").write_text("C", encoding="utf-8")
    sub = src / "sub"
    sub.mkdir()
    (sub / "d.md").write_text("MD", encoding="utf-8")
    (sub / "e.xyz").write_text("E", encoding="utf-8")
    return str(src)


def _register_source(temp_db, name, path):
    from models.source import DocumentSource
    db = temp_db()
    try:
        db.add(DocumentSource(id=name, name="源", path=path, source_type="local", is_deleted=False))
        db.commit()
    finally:
        db.close()


def _write_summary(source_id, rel, content_hash):
    from summary_generation.document import store as summary_store
    path = summary_store.summary_path(source_id, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"doc_name": rel, "structure": [], "content_hash": content_hash}, f)


class FakeTask:
    """最小 Task 形状：run_files_concurrently 只消费 stop_event"""

    def __init__(self):
        self.stop_event = threading.Event()


class TestListSupportedFiles:

    def test_recursive_scan_filters_extensions(self, src):
        files = scanner.list_supported_files(src)
        assert "a.md" in files
        assert "b.txt" in files
        assert "sub/d.md" in files
        assert "sub/e.xyz" not in files

    def test_subdir_entries_expand(self, src):
        files = scanner.list_supported_files(src, ["sub"])
        assert files == ["sub/d.md"]

    def test_escape_subdir_rejected(self, src):
        with pytest.raises(ValueError):
            scanner.list_supported_files(src, ["../elsewhere"])


class TestCollectSourceFiles:

    def test_none_means_full_scan(self, src):
        files, failures = scanner.collect_source_files(src, None)
        assert failures == []
        assert "a.md" in files and "sub/d.md" in files

    def test_dir_entry_expanded_and_deduped(self, src):
        files, failures = scanner.collect_source_files(src, ["sub", "sub"])
        assert files == ["sub/d.md"]
        assert failures == []

    def test_missing_entry_recorded_not_fatal(self, src):
        files, failures = scanner.collect_source_files(src, ["missing.md", "a.md"])
        assert files == ["a.md"]
        assert failures == [{"file": "missing.md", "reason": "文件不存在"}]

    def test_unsupported_entry_dropped(self, src):
        files, failures = scanner.collect_source_files(src, ["sub/e.xyz"])
        assert files == []
        assert failures == []

    def test_escape_entry_rejected(self, src):
        with pytest.raises(ValueError):
            scanner.collect_source_files(src, ["../x.md"])


class TestRunFilesConcurrently:

    def _run(self, files, worker, concurrency=2, task=None):
        agg = {"processed": []}
        task = task or FakeTask()

        def on_processed(done, total):
            agg["processed"].append((done, total))

        stats = run_files_concurrently(task, files, concurrency, worker, on_processed)
        return stats, agg["processed"], task

    def test_all_succeed(self):
        stats, processed, _ = self._run(["a", "b", "c"], lambda f: True, concurrency=3)
        assert stats["succeeded"] == 3
        assert stats["skipped"] == 0
        assert stats["failures"] == []
        assert processed[-1][0] == 3

    def test_worker_false_is_skipped(self):
        stats, _, _ = self._run(["a", "b"], lambda f: False)
        assert stats["skipped"] == 2
        assert stats["succeeded"] == 0

    def test_failure_isolated(self):
        def worker(f):
            if f == "bad":
                raise RuntimeError("boom")
            return True

        stats, _, _ = self._run(["good1", "bad", "good2"], worker)
        assert stats["succeeded"] == 2
        assert stats["failures"] == [{"file": "bad", "reason": "boom"}]

    def test_stop_cancels_pending(self):
        """stop 命中：未启动项取消计 skipped，已在跑的自然完成计 succeeded"""
        task = FakeTask()

        def worker(f):
            if f == "slow":
                task.stop_event.set()  # 模拟 stop_task 在执行期间置位
            return True

        stats, _, _ = self._run(["slow", "p1", "p2", "p3"], worker, concurrency=1, task=task)
        assert stats["succeeded"] == 1
        assert stats["skipped"] == 3
        assert stats["failures"] == []


class TestBatchSummaryHandler:

    def test_payload_contract(self):
        with pytest.raises(ValueError):
            DocumentBatchSummaryHandler.validate_payload({})
        DocumentBatchSummaryHandler.validate_payload({"source_id": "s1"})

    def test_no_model_fails_fast(self, monkeypatch):
        from summary_generation.document import llm

        monkeypatch.setattr(llm, "get_model_config", lambda: None)
        handler = DocumentBatchSummaryHandler()
        task = SimpleNamespace(payload={"source_id": "s1", "files": ["a.md"]},
                               stop_event=threading.Event())
        with pytest.raises(RuntimeError, match="没有可用的模型"):
            handler.execute(task, lambda p: None)

    def test_happy_path_counts_and_skip(self, monkeypatch, src, temp_db, tmp_path):
        """全量本走一遍：4 个可处理文件全成功；重跑时指纹一致全部 skipped"""
        from summary_generation.document import store as summary_store

        _register_source(temp_db, "s1", src)
        monkeypatch.setattr("config.database.SessionLocal", temp_db)
        monkeypatch.setattr(summary_store, "SUMMARY_ROOT", str(tmp_path / "summaries"))
        from summary_generation.document import llm

        monkeypatch.setattr(llm, "get_model_config", lambda: {"model": "x"})
        monkeypatch.setattr(
            summary_store, "generate",
            lambda full_path: {"doc_name": "x", "structure": [],
                               "content_hash": summary_store.file_content_hash(full_path)})

        handler = DocumentBatchSummaryHandler()
        task = SimpleNamespace(payload={"source_id": "s1"}, stop_event=threading.Event())
        result = handler.execute(task, lambda p: None)
        assert result["total"] == 4
        assert result["succeeded"] == 4
        assert result["skipped"] == 0
        assert result["failed"] == 0

        rerun = handler.execute(
            SimpleNamespace(payload={"source_id": "s1"}, stop_event=threading.Event()),
            lambda p: None)
        assert rerun["skipped"] == 4
        assert rerun["succeeded"] == 0

    def test_empty_collection_fails(self, monkeypatch, src, temp_db):
        _register_source(temp_db, "s1", src)
        monkeypatch.setattr("config.database.SessionLocal", temp_db)
        from summary_generation.document import llm

        monkeypatch.setattr(llm, "get_model_config", lambda: {"model": "x"})
        handler = DocumentBatchSummaryHandler()
        task = SimpleNamespace(
            payload={"source_id": "s1", "files": ["sub/e.xyz"]},  # 仅有不支持的扩展名
            stop_event=threading.Event())
        with pytest.raises(ValueError, match="没有可处理的文件"):
            handler.execute(task, lambda p: None)


class TestBatchExtractHandler:

    def test_payload_contract(self):
        with pytest.raises(ValueError):
            DocumentBatchExtractHandler.validate_payload({})
        DocumentBatchExtractHandler.validate_payload({"source_id": "s1"})


class TestDatasourceLabel:

    def test_batch_label_takes_precedence(self):
        """前端按勾选语义传的 batch_label 优先于条目数推断（勾目录 ≠ N 个文件）"""
        from task_management.task_manager import _datasource_label_from_payload

        payload = {"source_id": "s1", "files": ["sub/"], "batch_label": "sub/"}
        assert _datasource_label_from_payload(payload) == "sub/"

    def test_batch_label_fallback_counts_entries(self):
        from task_management.task_manager import _datasource_label_from_payload

        payload = {"source_id": "s1", "files": ["a.md", "b/"]}
        assert _datasource_label_from_payload(payload) == "s1（2 个文件）"
        full = {"source_id": "s1", "files": None}
        assert _datasource_label_from_payload(full) == "s1（全源）"

    def test_single_file_extract_with_label(self):
        from task_management.task_manager import _datasource_label_from_payload

        payload = {"source_id": "s1", "files": ["a.md"], "batch_label": "a.md"}
        assert _datasource_label_from_payload(payload) == "a.md"

    def test_no_model_fails_fast(self, monkeypatch):
        from model_management import model_service

        monkeypatch.setattr(model_service.ModelService, "get_available_model",
                            staticmethod(lambda db: None))
        handler = DocumentBatchExtractHandler()
        task = SimpleNamespace(payload={"source_id": "s1", "files": ["a.md"]},
                               stop_event=threading.Event())
        with pytest.raises(RuntimeError, match="没有可用的模型"):
            handler.execute(task, lambda p: None)

    def test_happy_path_with_missing_summary(self, monkeypatch, src, temp_db, tmp_path):
        """2 文件批：1 个有摘要成功、1 个缺摘要记 failure；统计口径正确"""
        from model_management import model_service
        import entity_extraction.document.service as entity_service
        import wiki_generation.service as wiki_mod
        from summary_generation.document import store as summary_store

        _register_source(temp_db, "s1", src)
        monkeypatch.setattr("config.database.SessionLocal", temp_db)
        monkeypatch.setattr(summary_store, "SUMMARY_ROOT", str(tmp_path / "summaries"))
        monkeypatch.setattr(model_service.ModelService, "get_available_model",
                            staticmethod(lambda db: {"model": "x"}))

        class FakeExtractor:
            def __init__(self, *args, **kwargs):
                pass

            def extract_from_summary(self, summary_path, datasource,
                                     parallelism, domain, evidence_hash=None):
                return {"entity_count": 2, "relationship_count": 1}

        monkeypatch.setattr(entity_service, "DocumentExtractionService", FakeExtractor)
        monkeypatch.setattr(wiki_mod, "wiki_service", SimpleNamespace(
            refresh_topics=lambda: [], generate_entity_pages=lambda: [],
            prune_orphans=lambda: 0))

        _write_summary("s1", "a.md", "h1")

        handler = DocumentBatchExtractHandler()
        task = SimpleNamespace(
            payload={"source_id": "s1", "files": ["a.md", "c.md"]},
            stop_event=threading.Event())
        result = handler.execute(task, lambda p: None)

        assert result["total"] == 2
        assert result["succeeded"] == 1
        assert result["failed"] == 1
        assert result["entity_count"] == 2
        assert result["relationship_count"] == 1
        assert result["failures"] == [{"file": "c.md", "reason": "摘要不存在，请先生成概要"}]
        assert result["wiki_pages"] == {"topic_pages": 0, "entity_pages": 0, "pruned_pages": 0}

    def test_zero_entity_is_valid_empty_output(self, monkeypatch, src, temp_db, tmp_path):
        """零实体守卫看批次是否全灭：抽 0 实体但调用成功 → 合法空产出，计入成功"""
        from model_management import model_service
        import entity_extraction.document.service as entity_service
        import wiki_generation.service as wiki_mod
        from summary_generation.document import store as summary_store

        _register_source(temp_db, "s1", src)
        monkeypatch.setattr("config.database.SessionLocal", temp_db)
        monkeypatch.setattr(summary_store, "SUMMARY_ROOT", str(tmp_path / "summaries"))
        monkeypatch.setattr(model_service.ModelService, "get_available_model",
                            staticmethod(lambda db: {"model": "x"}))

        class ZeroExtractor:
            def __init__(self, *args, **kwargs):
                pass

            def extract_from_summary(self, summary_path, datasource,
                                     parallelism, domain, evidence_hash=None):
                return {"entity_count": 0, "relationship_count": 0,
                        "batch_total": 2, "batch_failed": 0}

        monkeypatch.setattr(entity_service, "DocumentExtractionService", ZeroExtractor)
        monkeypatch.setattr(wiki_mod, "wiki_service", SimpleNamespace(
            refresh_topics=lambda: [], generate_entity_pages=lambda: [],
            prune_orphans=lambda: 0))

        _write_summary("s1", "a.md", "h1")

        handler = DocumentBatchExtractHandler()
        task = SimpleNamespace(payload={"source_id": "s1", "files": ["a.md"]},
                               stop_event=threading.Event())
        result = handler.execute(task, lambda p: None)
        assert result["succeeded"] == 1
        assert result["failed"] == 0
        assert result["entity_count"] == 0
        # 零产出跳过批后 Wiki 刷新（省一次全图扫描），null 即「没刷」的信号
        assert result["wiki_pages"] is None

    def test_all_batches_failed_guarded_as_failure(self, monkeypatch, src, temp_db, tmp_path):
        """零实体守卫反例：批次全部调用失败（大概率 LLM 不可用）→ 记 failure"""
        from model_management import model_service
        import entity_extraction.document.service as entity_service
        import wiki_generation.service as wiki_mod
        from summary_generation.document import store as summary_store

        _register_source(temp_db, "s1", src)
        monkeypatch.setattr("config.database.SessionLocal", temp_db)
        monkeypatch.setattr(summary_store, "SUMMARY_ROOT", str(tmp_path / "summaries"))
        monkeypatch.setattr(model_service.ModelService, "get_available_model",
                            staticmethod(lambda db: {"model": "x"}))

        class DeadExtractor:
            def __init__(self, *args, **kwargs):
                pass

            def extract_from_summary(self, summary_path, datasource,
                                     parallelism, domain, evidence_hash=None):
                return {"entity_count": 0, "relationship_count": 0,
                        "batch_total": 2, "batch_failed": 2}

        monkeypatch.setattr(entity_service, "DocumentExtractionService", DeadExtractor)
        monkeypatch.setattr(wiki_mod, "wiki_service", SimpleNamespace(
            refresh_topics=lambda: [], generate_entity_pages=lambda: [],
            prune_orphans=lambda: 0))

        _write_summary("s1", "a.md", "h1")

        handler = DocumentBatchExtractHandler()
        task = SimpleNamespace(payload={"source_id": "s1", "files": ["a.md"]},
                               stop_event=threading.Event())
        result = handler.execute(task, lambda p: None)
        assert result["succeeded"] == 0
        assert result["failed"] == 1
        assert "全部调用失败" in result["failures"][0]["reason"]
