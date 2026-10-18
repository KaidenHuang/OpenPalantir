"""
Wiki API 路由单元测试

最小 FastAPI 应用 + mock WikiService/task_manager，验证页面 CRUD、
生成任务参数编排（datasource / entity_id / scope）与入参校验。
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _create_test_app():
    from api.routes.wiki import router
    app = FastAPI()
    app.include_router(router, prefix="/api/wiki")
    return app


@pytest.fixture()
def client():
    return TestClient(_create_test_app())


@pytest.fixture()
def service():
    with patch("api.routes.wiki.wiki_service") as mock:
        yield mock


class TestPageCrud:

    def test_list_pages_passes_filters(self, client, service):
        service.list_pages.return_value = [{"page_id": "p1", "title": "页面"}]
        resp = client.get("/api/wiki/pages", params={"kind": "entity", "status": "draft"})

        assert resp.status_code == 200
        assert resp.json() == {"pages": [{"page_id": "p1", "title": "页面"}]}
        service.list_pages.assert_called_once_with(kind="entity", status="draft")

    def test_get_missing_page_404(self, client, service):
        service.get_page.return_value = None
        assert client.get("/api/wiki/pages/不存在").status_code == 404

    def test_update_page_404_when_absent(self, client, service):
        service.update_page.return_value = None
        resp = client.put("/api/wiki/pages/x", json={"content": "正文"})
        assert resp.status_code == 404

    def test_update_page_returns_page(self, client, service):
        service.update_page.return_value = {"page_id": "x", "content": "正文"}
        resp = client.put("/api/wiki/pages/x", json={"title": "标题", "content": "正文"})

        assert resp.status_code == 200
        service.update_page.assert_called_once_with("x", title="标题", content="正文")

    def test_delete_and_status(self, client, service):
        service.delete_page.return_value = True
        assert client.delete("/api/wiki/pages/x").json() == {"deleted": True}

        service.set_status.return_value = {"page_id": "x", "status": "published"}
        assert client.post("/api/wiki/pages/x/status",
                           json={"status": "published"}).status_code == 200
        assert client.post("/api/wiki/pages/x/status",
                           json={"status": "归档"}).status_code == 400


class TestPublishAnswer:

    def test_empty_answer_rejected(self, client, service):
        assert client.post("/api/wiki/publish_answer",
                           json={"question": "问题", "answer": "  "}).status_code == 400

    def test_publish_forwards_citations(self, client, service):
        service.publish_answer.return_value = {"page_id": "p", "kind": "answer"}
        resp = client.post("/api/wiki/publish_answer", json={
            "question": "谁负责平台？", "answer": "张三。",
            "citations": [{"datasource": "DOC://u/x.md", "node_id": "001", "title": "章节"}],
        })

        assert resp.status_code == 200
        service.publish_answer.assert_called_once_with(
            "谁负责平台？", "张三。",
            [{"datasource": "DOC://u/x.md", "node_id": "001", "title": "章节"}])


class TestGenerateTask:

    def test_datasource_takes_priority(self, client, service):
        with patch("task_management.task_manager.task_manager.create_task",
                   return_value="t1") as create:
            resp = client.post("/api/wiki/generate",
                               json={"datasource": "DOC://u/x.md", "scope": "topics"})

        assert resp.json() == {"task_id": "t1"}
        create.assert_called_once_with("wiki_generate", {"datasource": "DOC://u/x.md"})

    def test_entity_id_creates_single_entity_task(self, client, service):
        with patch("task_management.task_manager.task_manager.create_task",
                   return_value="t2") as create:
            resp = client.post("/api/wiki/generate", json={"entity_id": "abc123"})

        assert resp.status_code == 200
        create.assert_called_once_with("wiki_generate", {"entity_id": "abc123"})

    @pytest.mark.parametrize("scope", ["all", "topics", "entities"])
    def test_scopes_are_accepted(self, client, service, scope):
        with patch("task_management.task_manager.task_manager.create_task",
                   return_value="t3") as create:
            resp = client.post("/api/wiki/generate", json={"scope": scope})

        assert resp.status_code == 200
        create.assert_called_once_with("wiki_generate", {"scope": scope})

    def test_illegal_scope_rejected(self, client, service):
        with patch("task_management.task_manager.task_manager.create_task") as create:
            resp = client.post("/api/wiki/generate", json={"scope": "everything"})

        assert resp.status_code == 400
        create.assert_not_called()


class TestWikiGenerateHandler:

    def _task(self, payload):
        return SimpleNamespaceTask(payload)

    @pytest.mark.parametrize("payload,expected", [
        ({"datasource": "DOC://u/x.md"}, "generate_document_page"),
        ({"entity_id": "eid"}, "generate_entity_page"),
        ({"scope": "topics"}, "refresh_topics"),
        ({"scope": "entities"}, "generate_entity_pages"),
        ({"scope": "all"}, "generate_all"),
    ])
    def test_scope_dispatch(self, payload, expected):
        from task_management.handlers.wiki_generate import WikiGenerateHandler

        service = MagicMock()
        getattr(service, expected).return_value = []
        with patch("wiki.wiki_service.wiki_service", service):
            result = WikiGenerateHandler().execute(self._task(payload), lambda p: None)

        assert result["status"] == "success"
        getattr(service, expected).assert_called_once()


class SimpleNamespaceTask:
    def __init__(self, payload):
        self.payload = payload
        self.task_id = "t"
        self.task_type = "wiki_generate"
