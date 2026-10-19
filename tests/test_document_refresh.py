"""
文档内容失效传播测试

验证「指纹判定失效、按佐证回收图谱、先生成后回收的顺序、删除传播、
失效扫描、监听去重、刷新任务编排与 API 派发」。Neo4j / LLM / Wiki 全部 Mock 隔离。
"""
import hashlib
import itertools
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from document_processing import summary_generator
from pipeline import refresh
from task_management.handlers.document_refresh import DocumentRefreshHandler
import wiki.wiki_service  # noqa: F401  先执行模块导入
# wiki/__init__ 重导出同名单例，需经 sys.modules 取模块本体做属性 patch
ws_module = sys.modules["wiki.wiki_service"]


def md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def write_doc(env, rel, content):
    path = os.path.join(env["src"], rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content.encode("utf-8"))
    return path


def write_summary(env, source_id, rel, content_hash):
    path = summary_generator.summary_path(source_id, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"doc_name": rel, "structure": [], "content_hash": content_hash}, f)
    return path


@pytest.fixture()
def env(tmp_path, monkeypatch):
    src = tmp_path / "docs"
    src.mkdir()
    root = tmp_path / "summaries"
    root.mkdir()
    monkeypatch.setattr(summary_generator, "SUMMARY_ROOT", str(root))
    return {"src": str(src), "root": str(root)}


@pytest.fixture()
def source_db(temp_db, env):
    """注册一个本地文档源，并把 refresh / 路由指向临时库"""
    from models.source import DocumentSource

    db = temp_db()
    try:
        db.add(DocumentSource(id="s1", name="文档源", path=env["src"],
                              source_type="local", is_deleted=False))
        db.commit()
    finally:
        db.close()

    monkey = pytest.MonkeyPatch()
    monkey.setattr(refresh, "SessionLocal", temp_db)
    yield temp_db
    monkey.undo()


class TestStaleReason:

    def test_no_summary_is_not_stale(self, env):
        doc = write_doc(env, "a.md", "内容")
        assert refresh.stale_reason("s1", "a.md", doc) == ""

    def test_same_hash_is_not_stale(self, env):
        doc = write_doc(env, "a.md", "内容")
        write_summary(env, "s1", "a.md", md5("内容"))
        assert refresh.stale_reason("s1", "a.md", doc) == ""

    def test_changed_content(self, env):
        doc = write_doc(env, "a.md", "新内容")
        write_summary(env, "s1", "a.md", md5("旧内容"))
        assert refresh.stale_reason("s1", "a.md", doc) == "changed"

    def test_deleted_file(self, env):
        write_summary(env, "s1", "a.md", md5("内容"))
        missing = os.path.join(env["src"], "a.md")
        assert refresh.stale_reason("s1", "a.md", missing) == "removed"

    def test_broken_summary_is_not_stale(self, env):
        doc = write_doc(env, "a.md", "内容")
        path = summary_generator.summary_path("s1", "a.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{损坏的 json")
        assert refresh.stale_reason("s1", "a.md", doc) == ""


class TestGraphRecycle:
    """回收只摘本来源佐证，其他来源佐证的实体/边必须保留"""

    def test_entity_recycle_strips_evidence_before_delete(self):
        from knowledge_graph.entity_repository import EntityRepository
        from knowledge_graph import entity_repository as er

        conn = MagicMock()
        conn.execute_query.return_value = [{"deleted": 3}]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(er, "neo4j_conn", conn)
            assert EntityRepository().recycle_datasource("DOC://s1/") == 3

        query, params = conn.execute_query.call_args.args
        assert "ANY(d IN coalesce(n.datasources, []) WHERE d STARTS WITH $prefix)" in query
        assert "[d IN coalesce(n.datasources, []) WHERE NOT d STARTS WITH $prefix]" in query
        assert "WITH n WHERE size(coalesce(n.datasources, [])) = 0" in query
        assert "DETACH DELETE n" in query
        assert params == {"prefix": "DOC://s1/"}

    def test_relationship_recycle_keeps_edges_of_other_sources(self):
        from knowledge_graph.relationship_repository import RelationshipRepository
        from knowledge_graph import relationship_repository as rr

        conn = MagicMock()
        conn.execute_query.return_value = [{"deleted": 1}]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(rr, "neo4j_conn", conn)
            assert RelationshipRepository().recycle_datasource("DOC://s1/") == 1

        query, _ = conn.execute_query.call_args.args
        assert "MATCH ()-[r]->()" in query
        assert "[d IN coalesce(r.datasources, []) WHERE NOT d STARTS WITH $prefix]" in query
        assert "WITH r WHERE size(coalesce(r.datasources, [])) = 0" in query
        assert "DETACH" not in query

    def test_generation_recycle_keeps_new_evidence(self):
        """代际回收（keep_hash）：摘除本来源旧代佐证，保留 URI@keep_hash 新代条目"""
        from knowledge_graph.entity_repository import EntityRepository
        from knowledge_graph import entity_repository as er

        conn = MagicMock()
        conn.execute_query.return_value = [{"deleted": 2}]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(er, "neo4j_conn", conn)
            assert EntityRepository().recycle_datasource("DOC://s1/", keep_hash="abc") == 2

        query, params = conn.execute_query.call_args.args
        assert "WHERE NOT d STARTS WITH $prefix OR d ENDS WITH ('@' + $hash)]" in query
        assert params == {"prefix": "DOC://s1/", "hash": "abc"}
        # 主来源重算必须剥掉 @hash 代缀
        assert "split(coalesce(head(n.datasources), ''), '@')[0]" in query

    def test_relationship_generation_recycle(self):
        from knowledge_graph.relationship_repository import RelationshipRepository
        from knowledge_graph import relationship_repository as rr

        conn = MagicMock()
        conn.execute_query.return_value = [{"deleted": 0}]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(rr, "neo4j_conn", conn)
            RelationshipRepository().recycle_datasource("DOC://s1/", keep_hash="h2")

        query, params = conn.execute_query.call_args.args
        assert "WHERE NOT d STARTS WITH $prefix OR d ENDS WITH ('@' + $hash)]" in query
        assert params == {"prefix": "DOC://s1/", "hash": "h2"}

    def test_recycle_entrance_passes_keep_hash(self):
        """组合入口把 keep_hash 透传给边/实体两个回收实现"""
        from knowledge_graph import recycle

        got = []
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(recycle.rel_repo, "recycle_datasource",
                       lambda prefix, **kw: (got.append(("rel", kw.get("keep_hash"))), 0)[1])
            mp.setattr(recycle.entity_repo, "recycle_datasource",
                       lambda prefix, **kw: (got.append(("ent", kw.get("keep_hash"))), 0)[1])
            recycle.recycle_datasource("DOC://s1/", keep_hash="h9")
            assert got == [("rel", "h9"), ("ent", "h9")]

    def test_recycle_recycles_edges_then_entities(self):
        from knowledge_graph import recycle

        calls = []
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(recycle.rel_repo, "recycle_datasource",
                       lambda prefix, **kw: calls.append("edges") or 5)
            mp.setattr(recycle.entity_repo, "recycle_datasource",
                       lambda prefix, **kw: calls.append("entities") or 2)
            assert recycle.recycle_datasource("DOC://s1/") == {"edges": 5, "entities": 2}

        assert calls == ["edges", "entities"]


class TestRefreshDocument:

    def _stub_pipeline(self, mp, env, order, recycle_result=None):
        mp.setattr(refresh, "_source_base_path", lambda sid, quiet=False: env["src"])
        mp.setattr(refresh, "recycle_document",
                   lambda ds, keep_hash=None: (order.append(("recycle", keep_hash)),
                                               recycle_result or {"edges": 1, "entities": 1})[1])
        mp.setattr(refresh, "_extract",
                   lambda path, ds, domain, parallelism, evidence_hash=None:
                      (order.append(("extract", evidence_hash)),
                       {"entity_count": 4, "relationship_count": 2})[1])
        wiki = MagicMock()
        wiki.generate_document_page.return_value = {"page_id": "p1"}
        wiki.refresh_topics.return_value = [{}]
        wiki.generate_entity_pages.return_value = [{}, {}]
        wiki.prune_orphans.return_value = 0
        mp.setattr(ws_module, "wiki_service", wiki)
        return wiki

    def test_unchanged_without_force_is_skipped(self, env, source_db):
        doc = write_doc(env, "a.md", "内容")
        write_summary(env, "s1", "a.md", md5("内容"))
        result = refresh.refresh_document("s1", "a.md")
        assert result["status"] == "skipped"
        assert result["datasource"] == "DOC://s1/a.md"

    def test_extract_precedes_recycle_with_generation_mark(self, env, source_db):
        order = []
        write_doc(env, "a.md", "新内容")
        write_summary(env, "s1", "a.md", md5("旧内容"))

        with pytest.MonkeyPatch.context() as mp:
            self._stub_pipeline(mp, env, order)

            def fake_generate(full_path):
                order.append(("generate", None))
                return {"doc_name": "a.md", "structure": [],
                        "content_hash": md5("新内容")}

            def fake_save(source_id, file_path, data):
                order.append(("save", None))
                return summary_generator.summary_path(source_id, file_path)

            mp.setattr(summary_generator, "generate", fake_generate)
            mp.setattr(summary_generator, "save", fake_save)

            result = refresh.refresh_document("s1", "a.md")

        assert [item[0] for item in order] == ["generate", "save", "extract", "recycle"]
        assert result["status"] == "refreshed"
        assert result["reason"] == "changed"
        assert result["entity_count"] == 4
        assert result["document_page"] == "p1"
        assert result["topic_pages"] == 1
        assert result["entity_pages"] == 2
        # 代际编排：抽取带新 hash 佐证；回收只摘旧代（keep_hash=新 hash 保留新产出）
        assert order[2] == ("extract", md5("新内容"))
        assert order[3] == ("recycle", md5("新内容"))

    def test_summary_failure_leaves_old_graph_untouched(self, env, source_db):
        order = []
        write_doc(env, "a.md", "新内容")
        old_summary = write_summary(env, "s1", "a.md", md5("旧内容"))

        with pytest.MonkeyPatch.context() as mp:
            self._stub_pipeline(mp, env, order)
            mp.setattr(summary_generator, "generate",
                       MagicMock(side_effect=ConnectionError("LLM 不可用")))
            with pytest.raises(ConnectionError):
                refresh.refresh_document("s1", "a.md")

        assert order == []
        assert os.path.isfile(old_summary)

    def test_deleted_source_file_propagates_removal(self, env, source_db):
        write_summary(env, "s1", "a.md", md5("内容"))

        wiki = MagicMock()
        wiki.remove_pages_by_datasource.return_value = 2
        wiki.prune_orphans.return_value = 0
        recycled = MagicMock(return_value={"edges": 3, "entities": 1})
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(refresh, "_source_base_path", lambda sid, quiet=False: env["src"])
            mp.setattr(refresh, "recycle_document", recycled)
            mp.setattr(ws_module, "wiki_service", wiki)
            result = refresh.refresh_document("s1", "a.md")

        assert result["status"] == "removed"
        recycled.assert_called_once_with("DOC://s1/a.md")
        wiki.remove_pages_by_datasource.assert_called_once_with("DOC://s1/a.md")
        assert not os.path.exists(summary_generator.summary_path("s1", "a.md"))

    def test_force_refreshes_identical_content(self, env, source_db):
        order = []
        write_doc(env, "a.md", "内容")
        write_summary(env, "s1", "a.md", md5("内容"))

        with pytest.MonkeyPatch.context() as mp:
            self._stub_pipeline(mp, env, order)
            mp.setattr(summary_generator, "generate",
                       lambda p: {"doc_name": "a.md", "structure": [], "content_hash": md5("内容")})
            mp.setattr(summary_generator, "save",
                       lambda sid, rel, data: summary_generator.summary_path(sid, rel))
            result = refresh.refresh_document("s1", "a.md", force=True)

        assert result["status"] == "refreshed"
        assert result["reason"] == "forced"


class TestScanStale:

    def test_only_changed_and_removed_are_listed(self, env, source_db):
        write_doc(env, "keep.md", "内容")
        write_summary(env, "s1", "keep.md", md5("内容"))
        write_doc(env, "edit.md", "新")
        write_summary(env, "s1", "edit.md", md5("旧"))
        write_summary(env, "s1", "gone.md", md5("内容"))

        items = refresh.scan_stale()
        assert [(i["file_path"], i["reason"]) for i in items] == [
            ("edit.md", "changed"), ("gone.md", "removed")]

    def test_summary_of_deleted_source_is_ignored(self, env, temp_db):
        write_summary(env, "ghost", "a.md", md5("内容"))
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(refresh, "SessionLocal", temp_db)
            assert refresh.scan_stale() == []

    def test_resolve_file_rejects_escape(self, env):
        with pytest.raises(ValueError):
            refresh.resolve_file(env["src"], "../外部的.md")


class TestRefreshHandler:

    def test_missing_payload_raises(self):
        task = SimpleNamespace(task_id="t", task_type="document_refresh", payload={}, result=None)
        with pytest.raises(ValueError):
            DocumentRefreshHandler().execute(task, lambda p: None)

    def test_forwards_payload_and_progress(self):
        task = SimpleNamespace(task_id="t", task_type="document_refresh",
                               payload={"source_id": "s1", "file_path": "a.md",
                                        "force": True, "domain": "medical", "parallelism": 2},
                               result=None)
        progress = []
        with pytest.MonkeyPatch.context() as mp:
            fake = MagicMock(return_value={"status": "refreshed"})
            mp.setattr(refresh, "refresh_document", fake)
            result = DocumentRefreshHandler().execute(task, progress.append)

        assert result == {"status": "refreshed"}
        assert progress == [10, 100]
        fake.assert_called_once_with("s1", "a.md", force=True, domain="medical", parallelism=2)


class TestDocumentWatcher:

    def _watcher_env(self, mp, items, status="running"):
        from pipeline.watcher import DocumentWatcher

        counter = itertools.count(1)
        task_manager = MagicMock()
        task_manager.create_task.side_effect = lambda t, p: f"task-{next(counter)}"
        task_manager.get_task.return_value = SimpleNamespace(status=status)
        mp.setattr(refresh, "scan_stale", lambda *a, **kw: list(items))
        mp.setattr("task_management.task_manager.task_manager", task_manager)
        return DocumentWatcher(interval=5), task_manager

    def test_dispatches_one_task_per_stale_document(self):
        items = [{"source_id": "s1", "file_path": "a.md", "reason": "changed"},
                 {"source_id": "s1", "file_path": "b.md", "reason": "removed"}]
        with pytest.MonkeyPatch.context() as mp:
            watcher, task_manager = self._watcher_env(mp, items)
            dispatched = watcher.poll_once()

            assert [d["datasource"] for d in dispatched] == ["DOC://s1/a.md", "DOC://s1/b.md"]
            assert task_manager.create_task.call_count == 2
            assert task_manager.create_task.call_args_list[0].args[0] == "document_refresh"

    def test_inflight_document_is_not_dispatched_twice(self):
        items = [{"source_id": "s1", "file_path": "a.md", "reason": "changed"}]
        with pytest.MonkeyPatch.context() as mp:
            watcher, task_manager = self._watcher_env(mp, items)
            watcher.poll_once()
            assert watcher.poll_once() == []
            assert task_manager.create_task.call_count == 1

            task_manager.get_task.return_value = SimpleNamespace(status="completed")
            assert [d["task_id"] for d in watcher.poll_once()] == ["task-2"]

    def test_finished_task_is_released_even_when_still_stale(self):
        items = [{"source_id": "s1", "file_path": "a.md", "reason": "changed"}]
        with pytest.MonkeyPatch.context() as mp:
            watcher, task_manager = self._watcher_env(mp, items, status="failed")
            watcher.poll_once()
            assert len(watcher.poll_once()) == 1
            assert watcher.inflight["DOC://s1/a.md"] == "task-2"


class TestRefreshRoutes:

    @pytest.fixture()
    def client(self, temp_db):
        from api.routes.source import router
        from config.database import get_db

        app = FastAPI()
        app.include_router(router, prefix="/api")
        session = temp_db()
        app.dependency_overrides[get_db] = lambda: session
        yield TestClient(app)
        session.close()

    def test_refresh_creates_task(self, client, source_db):
        with pytest.MonkeyPatch.context() as mp:
            task_manager = MagicMock(create_task=MagicMock(return_value="t9"))
            mp.setattr("task_management.task_manager.task_manager", task_manager)
            resp = client.post("/api/sources/s1/refresh",
                               json={"file": "a.md", "force": True, "domain": "medical"})

        assert resp.status_code == 200
        assert resp.json()["task_id"] == "t9"
        task_type, payload = task_manager.create_task.call_args.args
        assert task_type == "document_refresh"
        assert payload == {"source_id": "s1", "file_path": "a.md",
                           "force": True, "domain": "medical", "parallelism": 8}

    def test_refresh_requires_file_and_existing_source(self, client, source_db):
        assert client.post("/api/sources/s1/refresh", json={}).status_code == 400
        assert client.post("/api/sources/不存在/refresh", json={"file": "a.md"}).status_code == 404

    def test_stale_listing_scans_source(self, client, env, temp_db, source_db):
        write_doc(env, "edit.md", "新")
        write_summary(env, "s1", "edit.md", md5("旧"))
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(refresh, "SessionLocal", temp_db)
            resp = client.get("/api/sources/s1/stale")

        assert resp.status_code == 200
        assert resp.json()["stale"][0]["file_path"] == "edit.md"
