"""
本体层单元测试

覆盖：本体包加载与校验、域视图合并、谓词归一化（含兜底）、relationship_id 一致性、
Cypher 关系类型白名单、定义域/值域校验、prompt 动态注入（文档抽取 + DB 标注两条路径对齐）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

import pytest

from models.ids import compute_relationship_id
from ontology import prompt as ontology_prompt
from ontology.predicates import (FALLBACK_PREDICATE, canonical_rel_id, cypher_rel_type,
                                 normalize_predicate)
from ontology.registry import OntologyRegistry, ontology_registry
from ontology.types import LinkType, ObjectType, OntologyError, OntologyPack


class TestPackLoading:

    def test_base_pack_and_domains(self):
        assert ontology_registry.get_link_type("包含", "general") is not None
        assert ontology_registry.get_object_type("other", "general") is not None
        assert "general" in ontology_registry.domains()

    def test_domain_view_extends_base(self):
        keys = {l.key for l in ontology_registry.link_types("workforce")}
        assert {"任职于", "管理"} <= keys
        assert {"包含", "依赖", "其他"} <= keys          # general 基底仍在
        obj_keys = {o.key for o in ontology_registry.object_types("workforce")}
        assert {"employee", "department", "position"} <= obj_keys
        assert ontology_registry.get_object_type("employee", "workforce").parent == "person"

    def test_unknown_domain_falls_back_to_general(self):
        assert {l.key for l in ontology_registry.link_types("不存在域")} == \
               {l.key for l in ontology_registry.link_types("general")}

    def test_missing_name_rejected(self):
        with pytest.raises(OntologyError):
            from ontology.registry import parse_pack
            parse_pack({"description": "无 name"})

    def test_validate_detects_dangling_references(self):
        from ontology.registry import validate_pack
        base = OntologyPack(name="general", object_types=[ObjectType(key="person", display_name="人物")])
        bad = OntologyPack(
            name="bad",
            object_types=[ObjectType(key="a", display_name="A", parent="ghost")],
            link_types=[LinkType(key="指向", domain=["ghost"], range=["missing"], inverse="反向")],
        )
        errors = validate_pack(bad, base=base)
        assert any("parent" in e for e in errors)
        assert any("domain" in e for e in errors)
        assert any("range" in e for e in errors)
        assert any("inverse" in e for e in errors)

    def test_register_pack_validates(self):
        with pytest.raises(OntologyError):
            ontology_registry.register_pack(OntologyPack(
                name="ghostly",
                link_types=[LinkType(key="幽灵", domain=["不存在的类型"])],
            ))


class TestDisplayNames:
    """界面显示中文、存储仍是英文 key：翻译只发生在读出的一侧"""

    def test_builtin_packs_have_chinese_display_names(self):
        assert ontology_registry.display_name("general") == "通用本体"
        assert ontology_registry.display_name("workforce") == "人力资源"

    def test_missing_display_name_falls_back_to_pack_name(self):
        from ontology.registry import parse_pack
        assert parse_pack({"name": "acme"}).display_name == ""

        registry = OntologyRegistry(packs_dir=ontology_registry._packs_dir,
                                   user_packs_dir="/nonexistent-dir")
        assert registry.display_name("general") == "通用本体"
        assert registry.display_name("不存在的域") == "不存在的域"

    def test_object_type_label_translates_key(self):
        assert ontology_registry.object_type_label("person") == "人物"
        # 只存在于域包里的类型也要翻得到（跨域视图查找）
        assert ontology_registry.object_type_label("employee") == "员工"
        assert ontology_registry.object_type_label("ghost_type") == "ghost_type"
        assert ontology_registry.object_type_label("") == ""

    def test_vocabulary_covers_every_domain(self):
        vocab = ontology_registry.vocabulary()
        types = {t["key"]: t["display_name"] for t in vocab["object_types"]}
        links = {t["key"]: t["display_name"] for t in vocab["link_types"]}

        assert {"person": "人物", "other": "其他", "employee": "员工"} == \
               {k: types[k] for k in ("person", "other", "employee")}
        assert "任职于" in links and "其他" in links
        assert {d["name"] for d in vocab["domains"]} == set(ontology_registry.domains())

    def test_export_keeps_pack_display_name(self):
        """导出即回读：显示名跟着 YAML 走，不能导一遍就丢"""
        import yaml

        from ontology.registry import parse_pack
        text = ontology_registry.export_pack("workforce")

        assert "display_name: 人力资源" in text
        assert parse_pack(yaml.safe_load(text)).display_name == "人力资源"


class TestPredicateNormalization:

    @pytest.mark.parametrize("raw,expected", [
        ("负责", "管理"),
        ("Foreign key", "依赖"),
        ("fk", "依赖"),
        ("外键", "依赖"),
        ("related to", "关联"),
        ("就职于", "任职于"),
        ("主治", "治疗"),
        ("  包含  ", "包含"),
    ])
    def test_aliases_resolve(self, raw, expected):
        key, hit = normalize_predicate(raw)
        assert hit is True
        assert key == expected

    @pytest.mark.parametrize("raw", ["精通量子力学", "", "RELATES_TO", "随意造的词"])
    def test_unknown_falls_back(self, raw):
        key, hit = normalize_predicate(raw)
        assert key == FALLBACK_PREDICATE
        assert hit is False

    def test_normalized_always_in_controlled_vocabulary(self):
        """验收项：任意输入经归一化后必落在受控词表内"""
        keys = set(ontology_registry.all_link_keys())
        samples = ["负责", "manages", "外键", "父子", "治疗", "无关词" * 3, "contains",
                   "隶属", "汇报于", "  ", "引用文献", "RELATES_TO"]
        for raw in samples:
            assert normalize_predicate(raw)[0] in keys

    def test_canonical_rel_id_uses_controlled_predicate(self):
        rel_id, key, hit = canonical_rel_id("张三", "负责", "平台")
        assert key == "管理" and hit is True
        assert rel_id == compute_relationship_id("张三", "管理", "平台")
        assert rel_id != compute_relationship_id("张三", "负责", "平台")

    def test_canonical_rel_id_fallback_keeps_raw_separate(self):
        rel_id, key, hit = canonical_rel_id("A", "精通量子力学", "B")
        assert key == FALLBACK_PREDICATE and hit is False
        assert rel_id == compute_relationship_id("A", "精通量子力学", "B")

    def test_canonical_rel_id_fallback_distinct_raw(self):
        first, _, _ = canonical_rel_id("A", "精通量子力学", "B")
        second, _, _ = canonical_rel_id("A", "研究玄学", "B")
        same_key, _, _ = canonical_rel_id("A", "精通量子力学", "B")
        assert first != second
        assert first == same_key


class TestRelationshipNormalizeGuard:
    """repository 写入前的归一化行：谓词必须受控；词表内 ID 用受控 key，词表外 ID 用原始谓词"""


    @pytest.mark.parametrize("raw_predicate", ["负责", "Foreign key", "同事", "", "关联"])
    def test_normalize_rel_rows(self, raw_predicate):
        from knowledge_graph.relationship_repository import _normalize_rel
        keys = set(ontology_registry.all_link_keys())
        row, hit = _normalize_rel({
            "subject": "张三", "object": "研发中心",
            "predicate": raw_predicate, "description": "d",
        })
        expected_key, expected_hit = normalize_predicate(raw_predicate)
        assert row["predicate"] == expected_key and hit is expected_hit
        assert row["predicate"] in keys
        id_key = row["predicate"] if (expected_hit or not raw_predicate.strip()) \
            else raw_predicate.strip()
        assert row["relationship_id"] == \
            compute_relationship_id("张三", id_key, "研发中心")
        assert row["raw_predicate"] == (
            raw_predicate if raw_predicate != row["predicate"] else "")

    def test_normalize_rel_evidence_defaults_to_datasource(self):
        """佐证条目默认纯 URI；带代际标记时按 origin URI@hash 原样透传"""
        from knowledge_graph.relationship_repository import _normalize_rel
        row, _ = _normalize_rel({"subject": "张三", "object": "研发中心",
                                 "predicate": "负责", "datasource": "DOC://s1/a.md"})
        assert row["evidence"] == "DOC://s1/a.md"

    def test_normalize_rel_generational_evidence(self):
        from knowledge_graph.relationship_repository import _normalize_rel
        row, _ = _normalize_rel({"subject": "张三", "object": "研发中心",
                                 "predicate": "负责", "datasource": "DOC://s1/a.md",
                                 "evidence": "DOC://s1/a.md@abc123"})
        assert row["evidence"] == "DOC://s1/a.md@abc123"


class TestDomainPlumbing:
    """domain 参数从 API 传到任务载荷，再决定注入哪套词表（两条导入路径的入口）"""

    @pytest.fixture()
    def client(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.routes import database as database_routes
        from task_management.task_manager import task_manager

        captured = {}

        def fake_create_task(task_type, payload):
            captured["task_type"] = task_type
            captured["payload"] = payload
            return "task-1"

        monkeypatch.setattr(task_manager, "create_task", fake_create_task)
        app = FastAPI()
        app.include_router(database_routes.router)
        yield TestClient(app), captured

    def test_analyze_forwards_domain(self, client):
        c, captured = client
        resp = c.post("/api/database/conn-1/analyze", json={"domain": "medical"})

        assert resp.status_code == 200
        assert captured["task_type"] == "database_schema_analyze"
        assert captured["payload"]["domain"] == "medical"

    def test_analyze_without_body_defaults_to_general(self, client):
        c, captured = client
        assert c.post("/api/database/conn-1/analyze").status_code == 200
        assert captured["payload"]["domain"] == "general"

    def test_analyze_empty_domain_defaults_to_general(self, client):
        c, captured = client
        c.post("/api/database/conn-1/analyze", json={"domain": None})
        assert captured["payload"]["domain"] == "general"


class TestCypherRelationType:

    def test_valid_keys_are_backticked(self):
        for key in ("包含", "任职于", FALLBACK_PREDICATE):
            assert cypher_rel_type(key) == f"`{key}`"

    @pytest.mark.parametrize("bad", ["", "不存在的谓词", "关联`", "a)-[r:evil", "related to"])
    def test_illegal_types_rejected(self, bad):
        with pytest.raises(OntologyError):
            cypher_rel_type(bad)

    def test_all_link_keys_are_cypher_safe(self):
        """词表本身必须可安全插值（索引预建依赖此不变量）"""
        for key in ontology_registry.all_link_keys():
            assert "`" not in key
            cypher_rel_type(key)


class TestDomainRangeValidation:

    def test_valid_types_pass(self):
        ok, reason = ontology_registry.validate_predicate_types("任职于", "employee", "department",
                                                                domain="workforce")
        assert ok is True and reason == ""

    def test_out_of_domain_rejected(self):
        ok, reason = ontology_registry.validate_predicate_types("任职于", "disease", "department",
                                                                domain="workforce")
        assert ok is False and "定义域" in reason

    def test_unknown_predicate_rejected(self):
        ok, reason = ontology_registry.validate_predicate_types("幽灵", "person", "person")
        assert ok is False and "受控词表" in reason

    def test_unrestricted_link_accepts_any_type(self):
        assert ontology_registry.validate_predicate_types("关联", "disease", "drug")[0] is True


class TestPromptInjection:

    def setup_method(self):
        ontology_prompt.clear_cache()

    def test_sections_render_registry_content(self):
        sections = ontology_prompt.prompt_sections("workforce")
        assert "- employee: " in sections["entity_types"]
        assert "person 的子类型" in sections["entity_types"]
        assert "- 任职于: " in sections["link_types"]
        assert "- 包含: " in sections["link_types"]
        # 属性词表：无声明时回落提示语，保证 prompt 占位符永远可替换
        assert "property_types" in sections
        assert sections["property_types"]

    def test_sections_are_cached(self):
        assert ontology_prompt.prompt_sections("general") is \
               ontology_prompt.prompt_sections("general")

    def test_document_extraction_prompt_aligned_with_ontology(self):
        from entity_extraction.document.extractor import LLMEntityEnhancer
        prompt = LLMEntityEnhancer()._build_combined_prompt("张三负责平台", domain="workforce")
        assert "{entity_types}" not in prompt and "{link_types}" not in prompt
        assert "{property_types}" not in prompt
        assert "- 任职于: " in prompt
        assert "- person: " in prompt
        assert "张三负责平台" in prompt

    def test_db_annotate_prompt_aligned_with_ontology(self):
        from summary_generation.database.annotator import SchemaAnnotator
        from model_management.model_client import ModelConfig
        annotator = SchemaAnnotator(model_config=ModelConfig(), domain="workforce")
        prompt = annotator._build_annotate_prompt({
            "tables": [{"table_name": "employee", "table_type": "BASE TABLE"}],
            "columns": [{"table_name": "employee", "column_name": "dept_id",
                         "data_type": "int"}],
            "foreign_keys": [{"table_name": "employee", "column_name": "dept_id",
                              "referenced_table_name": "department",
                              "referenced_column_name": "id"}],
        })
        assert "{entity_types}" not in prompt and "{link_types}" not in prompt
        assert "- 任职于: " in prompt and "- employee: " in prompt

    def test_both_paths_share_one_vocabulary(self):
        from entity_extraction.document.extractor import LLMEntityEnhancer
        from summary_generation.database.annotator import SchemaAnnotator
        from model_management.model_client import ModelConfig

        doc = LLMEntityEnhancer()._build_combined_prompt("文本", domain="medical")
        db = SchemaAnnotator(model_config=ModelConfig(), domain="medical") \
            ._build_annotate_prompt({"tables": [], "columns": [], "foreign_keys": []})
        vocab = [l.key for l in ontology_registry.link_types("medical")]
        for key in vocab:
            assert f"- {key}: " in doc and f"- {key}: " in db
