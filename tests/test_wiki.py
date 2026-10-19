"""
Wiki 模块单元测试

测试 page_generator（文档页/主题页）、entity_generator（实体页）、WikiService（CRUD、发布、互链）。
LLM、摘要文件与 Neo4j 均被隔离（Stub client + 临时摘要目录 + 临时 SQLite + Fake neo4j_conn）。
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

import pytest

from summary_generation.document import store as summary_generator
from wiki_generation.document import generator as page_generator
from wiki_generation.entity import generator as entity_generator
import wiki_generation.service  # noqa: F401  先执行模块导入
from wiki_generation.service import WikiService
# wiki_generation/__init__ 重导出同名单例，需经 sys.modules 取模块本体做属性 patch
ws_module = sys.modules["wiki_generation.service"]
# 确保 wiki_pages / embedding_cache 表注册进 Base.metadata（temp_db 建表用）
from models.wiki import WikiPage  # noqa: F401
from models.embedding import EmbeddingCache  # noqa: F401


class StubClient:
    """Wiki 生成用 LLM 桩：reply 为 None 时模拟调用失败"""

    def __init__(self, reply=None):
        self.reply = reply
        self.calls = 0
        self.prompts = []
        self.config = SimpleNamespace(embedding_model="bge-m3")

    def call_text(self, prompt, **kwargs):
        self.calls += 1
        self.prompts.append(prompt)
        if self.reply is None:
            raise ConnectionError("LLM 不可用")
        return self.reply


def make_node(node_id, title, summary, text="原文内容", nodes=None):
    return {"title": title, "node_id": node_id, "summary": summary,
            "text": text, "nodes": nodes or []}


def write_summary(summaries_dir, uuid, doc_name, structure, description):
    os.makedirs(os.path.join(summaries_dir, "DOC", uuid), exist_ok=True)
    path = os.path.join(summaries_dir, "DOC", uuid, doc_name + ".json")
    data = {"doc_name": doc_name, "doc_description": description, "structure": structure}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


@pytest.fixture()
def wiki_env(temp_db, monkeypatch):
    tmpdir = tempfile.mkdtemp()
    summaries_dir = os.path.join(tmpdir, "summaries")
    monkeypatch.setattr(summary_generator, "SUMMARY_ROOT", summaries_dir)
    monkeypatch.setattr(ws_module, "SessionLocal", temp_db)
    stub = StubClient(reply="# 团队概览\n\n本页汇总团队成员与职责。")
    monkeypatch.setattr("model_management.model_client.get_model_client", lambda: stub)
    yield SimpleNamespace(dir=summaries_dir, service=WikiService(), stub=stub,
                          tmpdir=tmpdir, db=temp_db)
    shutil.rmtree(tmpdir, ignore_errors=True)


def row(db_session, page_id):
    db = db_session()
    try:
        return db.query(WikiPage).filter_by(page_id=page_id).first()
    finally:
        db.close()


class TestDocumentPage:

    def test_generate_with_llm(self, wiki_env):
        env = wiki_env
        path = write_summary(env.dir, "u1", "团队介绍.md", [
            make_node("001", "成员", "介绍团队成员"),
            make_node("002", "职责", "团队职责划分"),
        ], "全员名单与分工")
        datasource = "DOC://u1/团队介绍.md"
        page = env.service.generate_document_page(datasource)

        assert page is not None
        assert page["kind"] == "document"
        assert page["title"] == "团队概览"
        assert "## 参考来源" in page["content"]
        assert page["datasource"] == datasource
        assert row(env.db, page["page_id"]).source_hash == \
            hashlib.md5(open(path, "rb").read()).hexdigest()
        assert len(page["source_refs"]) == 2
        assert page["source_refs"][0]["node_id"] == "001"

    def test_fallback_when_llm_fails(self, wiki_env):
        env = wiki_env
        env.stub.reply = None
        write_summary(env.dir, "u1", "团队介绍.md", [
            make_node("001", "成员", "介绍团队成员"),
        ], "全员名单")
        page = env.service.generate_document_page("DOC://u1/团队介绍.md")

        assert page is not None
        assert page["content"].startswith("# 团队介绍.md")
        assert "[1]" in page["content"]

    def test_no_summary_returns_none(self, wiki_env):
        assert wiki_env.service.generate_document_page("DOC://missing/x.md") is None

    def test_regenerate_unchanged_skips(self, wiki_env):
        env = wiki_env
        write_summary(env.dir, "u1", "团队介绍.md", [make_node("001", "成员", "介绍团队")], "全员名单")
        first = env.service.generate_document_page("DOC://u1/团队介绍.md")
        second = env.service.generate_document_page("DOC://u1/团队介绍.md")

        assert second["page_id"] == first["page_id"]
        assert len(env.service.list_pages(kind="document")) == 1

    def test_regenerate_after_source_change_updates_in_place(self, wiki_env):
        env = wiki_env
        path = write_summary(env.dir, "u1", "团队介绍.md",
                             [make_node("001", "成员", "介绍团队")], "全员名单")
        first = env.service.generate_document_page("DOC://u1/团队介绍.md")

        write_summary(env.dir, "u1", "团队介绍.md", [
            make_node("001", "成员", "介绍团队"),
            make_node("002", "职责", "职责划分"),
        ], "全员名单与分工")
        second = env.service.generate_document_page("DOC://u1/团队介绍.md")

        assert second["page_id"] == first["page_id"]
        expected = hashlib.md5(open(path, "rb").read()).hexdigest()
        assert row(env.db, second["page_id"]).source_hash == expected
        assert len(second["source_refs"]) == 2


class TestTopicPage:

    def test_discover_topics_shared_keyword(self, wiki_env):
        env = wiki_env
        write_summary(env.dir, "u1", "考核办法.md",
                      [make_node("001", "绩效体系", "公司绩效框架")], "季度评估细则")
        write_summary(env.dir, "u2", "员工手册.md",
                      [make_node("010", "绩效评估", "绩效如何评估员工")], "入职须知")
        write_summary(env.dir, "u3", "备份指南.md",
                      [make_node("020", "数据库备份", "备份策略说明")], "运维操作")

        topics = page_generator.discover_topics(min_docs=2, top_n=3)
        names = [t for t, _ in topics]
        assert "绩效" in names
        fragments = dict(topics)["绩效"]
        ds_set = {f["datasource"] for f in fragments}
        assert ds_set == {"DOC://u1/考核办法.md", "DOC://u2/员工手册.md"}

    def test_discover_topics_requires_two_docs(self, wiki_env):
        env = wiki_env
        write_summary(env.dir, "u1", "考核办法.md",
                      [make_node("001", "绩效体系", "说明")], "季度评估细则")
        assert page_generator.discover_topics(min_docs=2) == []

    def test_generate_topic_page_and_dedup(self, wiki_env):
        env = wiki_env
        fragments = [
            {"datasource": "DOC://u1/A.md", "node_id": "001", "title": "绩效制度", "summary": "s1"},
            {"datasource": "DOC://u2/B.md", "node_id": "010", "title": "绩效考核", "summary": "s2"},
        ]
        first = env.service.generate_topic_page("绩效", fragments)
        second = env.service.generate_topic_page("绩效", fragments)

        assert first["kind"] == "topic"
        assert second["page_id"] == first["page_id"]
        assert row(env.db, first["page_id"]).source_hash != ""
        assert "## 参考来源" in first["content"]

    def test_generate_topic_page_empty_fragments(self, wiki_env):
        assert page_generator.generate_topic_page("x", []) is None


class TestWikiServiceCrud:

    def test_publish_answer(self, wiki_env):
        env = wiki_env
        page = env.service.publish_answer(
            "张三的职责是什么？\n补充说明",
            "张三负责后端开发。",
            [{"datasource": "DOC://u1/x.md", "node_id": "001", "title": "成员"}],
        )
        assert page["kind"] == "answer"
        assert page["status"] == "published"
        assert page["title"] == "张三的职责是什么？"
        assert page["content"].startswith("> 问题：张三的职责是什么？")
        assert page["source_refs"][0]["n"] == 1
        assert "## 参考来源" in page["content"]

    def test_update_and_delete(self, wiki_env):
        env = wiki_env
        page = env.service.publish_answer("问题", "答案")
        new_content = "# 手工修改\n\n内容"
        updated = env.service.update_page(page["page_id"], title="新标题", content=new_content)

        assert updated["title"] == "新标题"
        assert updated["content"] == new_content
        assert row(env.db, page["page_id"]).content_hash == \
            hashlib.md5(new_content.encode("utf-8")).hexdigest()

        assert env.service.delete_page(page["page_id"]) is True
        assert env.service.delete_page(page["page_id"]) is False
        assert env.service.get_page(page["page_id"]) is None

    def test_status_and_filters(self, wiki_env):
        env = wiki_env
        p1 = env.service.publish_answer("问答一", "答案一")
        env.service.set_status(p1["page_id"], "draft")
        env.service.publish_answer("问答二", "答案二")

        published = env.service.list_pages(kind="answer", status="published")
        drafts = env.service.list_pages(kind="answer", status="draft")
        assert len(published) == 1
        assert published[0]["title"] == "问答二"
        assert len(drafts) == 1
        assert env.service.set_status("不存在", "published") is None

    def test_extract_links(self, wiki_env):
        env = wiki_env
        env.service.publish_answer("绩效改革方案", "背景说明")
        second = env.service.publish_answer(
            "问答", "本方案参考了绩效改革方案一文。")
        assert "绩效改革方案" in second["links"]


class TestAppendReferences:

    def test_format(self):
        from wiki_generation.service import _append_references
        out = _append_references("正文", [
            {"n": 1, "datasource": "DOC://u/x.md", "node_id": "001", "title": "章节"},
            {"n": 2, "datasource": "DOC://u/y.md", "node_id": "", "title": ""},
        ])
        assert "[1] 章节（`DOC://u/x.md` #001）" in out
        # 无 node_id 时不输出锚点，title 空时回退 node（此处为空）
        assert "[2] " in out

    def test_empty_refs_noop(self):
        from wiki_generation.service import _append_references
        assert _append_references("正文", []) == "正文"


class FakeNeo4j:
    """按 Cypher 片断分发到内存图数据，隔离实体页查询"""

    def __init__(self, entities=None, edges=None):
        self.entities = entities or []
        self.edges = edges or []

    def execute_query(self, query, params=None):
        params = params or {}
        if "UNWIND $ids" in query:
            ids = set(params.get("ids") or [])
            return [e for e in self.edges if e["entity_id"] in ids]
        if "{id: $id}" in query:
            return [e for e in self.entities
                    if e["entity_id"] == params.get("id")]
        rows = [e for e in self.entities if e["degree"] >= params.get("min_degree", 0)]
        rows.sort(key=lambda r: -r["degree"])
        return rows[:params.get("limit", 20)]


def entity_row(entity_id, name, etype="person", description="", byname=None,
               datasource="DOC://u1/x.md", attributes=None, mention_count=1, degree=2):
    return {
        "entity_id": entity_id, "name": name, "type": etype,
        "description": description, "byname": byname, "datasource": datasource,
        "attributes": attributes if attributes is not None else json.dumps(
            {"工号": "A001"}, ensure_ascii=False),
        "mention_count": mention_count, "degree": degree,
    }


def edge_pair(a, b, predicate, raw="", description="共事"):
    """无向查询会为每条边产出锚定两端的两行"""
    common = {"predicate": predicate, "raw_predicate": raw,
              "description": description, "occurrence_time": ""}
    return [
        {**common, "entity_id": a["entity_id"], "subject_id": a["entity_id"],
         "subject": a["name"], "object_id": b["entity_id"], "object": b["name"],
         "other_id": b["entity_id"], "other_name": b["name"],
         "other_type": b["type"], "other_datasource": b["datasource"]},
        {**common, "entity_id": b["entity_id"], "subject_id": a["entity_id"],
         "subject": a["name"], "object_id": b["entity_id"], "object": b["name"],
         "other_id": a["entity_id"], "other_name": a["name"],
         "other_type": a["type"], "other_datasource": a["datasource"]},
    ]


@pytest.fixture()
def graph_env(wiki_env, monkeypatch):
    """在 wiki_env 之上接入 Fake Neo4j（张三 →管理→ 研发平台）"""
    zs = entity_row("id_zs", "张三", description="研发中心负责人")
    pf = entity_row("id_pf", "研发平台", etype="concept", datasource="DBS://u2/db.t",
                    attributes="{}")
    fake = FakeNeo4j([zs, pf], edge_pair(zs, pf, "管理", raw="负责"))
    monkeypatch.setattr(entity_generator, "neo4j_conn", fake)
    wiki_env.graph = fake
    yield wiki_env


class TestEntityPage:

    def test_generate_with_llm(self, graph_env):
        env = graph_env
        env.stub.reply = "# 张三\n\n其负责研发平台 [1]。"
        pages = env.service.generate_entity_pages(min_degree=2)

        assert [p["kind"] for p in pages] == ["entity"] * len(pages)
        zs_page = next(p for p in pages if p["title"] == "张三")
        assert zs_page["datasource"] == "ENT://id_zs/张三"
        assert "其负责研发平台" in zs_page["content"]
        assert "## 参考来源" in zs_page["content"]
        assert zs_page["source_refs"][0] == {"n": 1, "datasource": "DOC://u1/x.md",
                                            "node_id": "id_zs", "title": "张三"}
        assert {r["title"] for r in zs_page["source_refs"]} == {"张三", "研发平台"}

    def test_fallback_when_llm_fails(self, graph_env):
        env = graph_env
        env.stub.reply = None
        page = env.service.generate_entity_pages(min_degree=2)[0]

        assert page["content"].startswith("# 张三")
        assert "研发中心负责人" in page["content"]
        assert "张三 → 管理 → 研发平台（原文：负责）" in page["content"]
        assert "工号：A001" in page["content"]
        assert "类型：人物" in page["content"]
        assert "person" not in page["content"]

    def test_llm_prompt_uses_chinese_type_label(self, graph_env):
        """喂给模型的档案也要中文：否则生成页会把 person 这类标识抄进正文"""
        env = graph_env
        env.service.generate_entity_pages(min_degree=2)
        joined = "\n".join(env.stub.prompts)

        assert "- 类型：人物" in joined and "- 类型：概念" in joined
        assert "- 类型：person" not in joined and "- 类型：concept" not in joined

    def test_type_outside_ontology_shown_verbatim(self, graph_env):
        """词表外的历史 key 不硬翻：宁可露出标识，也不显示空白或错名字"""
        env = graph_env
        env.stub.reply = None
        env.graph.entities = [
            entity_row("id_zs", "张三", etype="ghost_type"),
            next(e for e in env.graph.entities if e["entity_id"] == "id_pf"),
        ]
        page = next(p for p in env.service.generate_entity_pages(min_degree=2)
                    if p["title"] == "张三")

        assert "类型：ghost_type" in page["content"]

    def test_regenerate_unchanged_skips(self, graph_env):
        env = graph_env
        first = env.service.generate_entity_pages(min_degree=2)
        second = env.service.generate_entity_pages(min_degree=2)

        assert [p["page_id"] for p in second] == [p["page_id"] for p in first]
        assert len(env.service.list_pages(kind="entity")) == len(first)

    def test_regenerate_after_graph_change_updates_in_place(self, graph_env):
        env = graph_env
        env.stub.reply = None
        first = next(p for p in env.service.generate_entity_pages(min_degree=2)
                     if p["title"] == "张三")
        first_hash = row(env.db, first["page_id"]).source_hash

        env.graph.entities = [
            entity_row("id_zs", "张三", description="已转岗至数据部门"),
            next(e for e in env.graph.entities if e["entity_id"] == "id_pf"),
        ]
        second = next(p for p in env.service.generate_entity_pages(min_degree=2)
                      if p["title"] == "张三")

        assert second["page_id"] == first["page_id"]
        assert "已转岗至数据部门" in second["content"]
        assert row(env.db, second["page_id"]).source_hash != first_hash

    def test_generate_single_entity_by_id(self, graph_env):
        env = graph_env
        page = env.service.generate_entity_page("id_pf")

        assert page["title"] == "研发平台"
        assert page["datasource"] == "ENT://id_pf/研发平台"
        assert env.service.generate_entity_page("不存在") is None

    def test_entity_without_relationships_skipped(self, graph_env):
        env = graph_env
        env.graph.edges = []
        assert env.service.generate_entity_pages(min_degree=0) == []

    def test_cross_links_between_entity_pages(self, graph_env):
        env = graph_env
        env.stub.reply = None
        env.service.generate_entity_pages(min_degree=2)
        by_title = {p["title"]: p for p in env.service.list_pages(kind="entity")}

        assert "研发平台" in by_title["张三"]["links"]
        assert "张三" in by_title["研发平台"]["links"]


class TestOrphanPruning:
    """失效传播最后一环：来源消失后页面必须被清理，且不误删其他来源的页面"""

    def _save(self, service, kind, datasource, title):
        return service._save_page({"title": title, "kind": kind,
                                   "content": f"# {title}", "datasource": datasource})

    def test_remove_pages_by_datasource(self, wiki_env):
        env = wiki_env
        self._save(env.service, "document", "DOC://u1/团队介绍.md", "团队介绍")
        self._save(env.service, "document", "DOC://u2/员工手册.md", "员工手册")

        assert env.service.remove_pages_by_datasource("DOC://u1/团队介绍.md") == 1
        assert [p["title"] for p in env.service.list_pages(kind="document")] == ["员工手册"]

    def test_document_page_pruned_when_summary_deleted(self, wiki_env):
        env = wiki_env
        write_summary(env.dir, "u1", "团队介绍.md", [make_node("001", "成员", "s")], "描述")
        self._save(env.service, "document", "DOC://u1/团队介绍.md", "团队介绍")
        os.remove(summary_generator.summary_path("u1", "团队介绍.md"))

        assert env.service.prune_orphans() == 1
        assert env.service.list_pages(kind="document") == []

    def test_entity_page_pruned_when_entity_recycled(self, wiki_env, monkeypatch):
        env = wiki_env
        self._save(env.service, "entity", "ENT://id_zs/张三", "张三")
        self._save(env.service, "entity", "ENT://id_pf/研发平台", "研发平台")
        repo = SimpleNamespace(get_entities_batch=lambda ids, strict=False: {i: {} for i in ids if i != "id_zs"})
        monkeypatch.setattr("knowledge_graph.entity_repository.entity_repo", repo)

        assert env.service.prune_orphans() == 1
        assert [p["title"] for p in env.service.list_pages(kind="entity")] == ["研发平台"]

    def test_topic_and_answer_pages_are_not_pruned(self, wiki_env, monkeypatch):
        env = wiki_env
        self._save(env.service, "topic", "", "绩效")
        self._save(env.service, "answer", "", "问答沉淀")
        repo = SimpleNamespace(get_entities_batch=lambda ids, strict=False: {})
        monkeypatch.setattr("knowledge_graph.entity_repository.entity_repo", repo)

        assert env.service.prune_orphans() == 0
        assert len(env.service.list_pages()) == 2
