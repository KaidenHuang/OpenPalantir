"""
本体治理与本体包导入导出测试

覆盖「词表使用统计、非法类型/谓词/定义域值域检测、结构问题清单、
社区包导入即校验、导出可回读、用户包覆盖内置包、新谓词贯通归一化→类型化边」。
图谱聚合查询以 Mock 隔离，不依赖 Neo4j。
"""
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ontology import governance
from ontology import predicates as predicates_module
from ontology.registry import PACKS_DIR, OntologyRegistry, parse_pack
from ontology.types import OntologyError

BASE_PACK_YAML = """
name: general
description: 基底包
object_types:
  - key: person
    display_name: 人物
  - key: organization
    display_name: 组织
  - key: other
    display_name: 其他
link_types:
  - key: 管理
    display_name: 管理
    domain: [person]
    range: [organization]
    aliases: [负责]
  - key: 其他
    display_name: 其他
"""

COMMUNITY_PACK_YAML = """
name: logistics
description: 物流领域包
object_types:
  - key: warehouse
    display_name: 仓库
    parent: organization
  - key: shipment
    display_name: 运单
link_types:
  - key: 存放于
    display_name: 存放于
    domain: [shipment]
    range: [warehouse]
    aliases: [入库到]
"""


@pytest.fixture()
def registry(tmp_path):
    packs = tmp_path / "packs"
    packs.mkdir()
    (packs / "general.yaml").write_text(BASE_PACK_YAML, encoding="utf-8")
    user = tmp_path / "user_packs"
    reg = OntologyRegistry(packs_dir=str(packs), user_packs_dir=str(user))
    reg.load()
    return reg


class FakeGraph:
    def __init__(self, predicate_usage=None, type_usage=None, pairs=None,
                 variants=None, isolated=None, placeholders=None, gaps=None):
        self._predicate_usage = predicate_usage or {}
        self._type_usage = type_usage or {}
        self._pairs = pairs or []
        self._variants = variants or []
        self._isolated = isolated or []
        self._placeholders = placeholders or []
        self._gaps = gaps or {"entities": 0, "relationships": 0}

    def predicate_usage(self):
        return self._predicate_usage

    def type_usage(self):
        return self._type_usage

    def endpoint_type_pairs(self):
        return self._pairs

    def raw_predicate_variants(self, limit=200):
        return self._variants[:limit]

    def isolated_entities(self, limit=50):
        return self._isolated[:limit]

    def placeholder_entities(self, limit=50):
        return self._placeholders[:limit]

    def provenance_gaps(self):
        return self._gaps


def use_graph(mp, fake):
    mp.setattr("knowledge_graph.graph_manager.graph_manager", fake)


class TestPackImportExport:

    def test_export_roundtrip_is_identical(self, registry):
        exported = registry.export_pack("general")
        reparsed = parse_pack(yaml.safe_load(exported))

        assert reparsed == registry.pack("general")

    def test_unknown_domain_export_rejected(self, registry):
        with pytest.raises(OntologyError):
            registry.export_pack("不存在")

    def test_import_registers_and_extends_vocabulary(self, registry):
        pack = registry.import_pack(COMMUNITY_PACK_YAML)

        assert pack.name == "logistics"
        assert registry.domains() == ["general", "logistics"]
        assert registry.resolve_predicate_any("入库到") == "存放于"
        assert registry.is_link_key("存放于")

    def test_invalid_pack_is_rejected_and_not_registered(self, registry):
        broken = COMMUNITY_PACK_YAML.replace("range: [warehouse]", "range: [ghost_type]")
        with pytest.raises(OntologyError) as err:
            registry.import_pack(broken)

        assert "ghost_type" in str(err.value)
        assert "logistics" not in registry.domains()

    def test_persist_writes_user_pack_and_survives_reload(self, registry, tmp_path):
        registry.import_pack(COMMUNITY_PACK_YAML, persist=True)
        target = tmp_path / "user_packs" / "logistics.yaml"
        assert target.is_file()

        registry.reload()
        assert registry.resolve_predicate_any("存放于") == "存放于"

    def test_general_cannot_be_persisted_over(self, registry):
        with pytest.raises(OntologyError):
            registry.import_pack(BASE_PACK_YAML, persist=True)

    def test_user_pack_overrides_builtin(self, tmp_path):
        packs = tmp_path / "packs"
        packs.mkdir()
        (packs / "general.yaml").write_text(BASE_PACK_YAML, encoding="utf-8")
        user = tmp_path / "user_packs"
        user.mkdir()
        (user / "general.yaml").write_text(
            BASE_PACK_YAML + "  - key: 隶属\n    display_name: 隶属\n", encoding="utf-8")

        reg = OntologyRegistry(packs_dir=str(packs), user_packs_dir=str(user))
        reg.load()

        assert reg.is_link_key("隶属")

    def test_community_pack_reaches_typed_edge_write(self, patched_predicates):
        """社区包导入后，其谓词能直接成为 Neo4j 类型化边（词表 → 归一化 → Cypher 类型名）"""
        query = predicates_module.cypher_rel_type("存放于")
        assert query == "`存放于`"
        rel_id, key, hit = predicates_module.canonical_rel_id("运单A", "入库到", "中心仓")
        assert (key, hit) == ("存放于", True)
        assert rel_id


@pytest.fixture()
def patched_predicates(monkeypatch, tmp_path):
    packs = tmp_path / "packs"
    packs.mkdir()
    (packs / "general.yaml").write_text(BASE_PACK_YAML, encoding="utf-8")
    reg = OntologyRegistry(packs_dir=str(packs), user_packs_dir=str(tmp_path / "user"))
    reg.load()
    reg.import_pack(COMMUNITY_PACK_YAML)
    monkeypatch.setattr(predicates_module, "ontology_registry", reg)
    return reg


EXTENDS_PACK_YAML = """
name: warehouse_ops
description: 在 logistics 之上扩展的二级包
extends: logistics
object_types:
  - key: pallet
    display_name: 托盘
link_types:
  - key: 装载于
    display_name: 装载于
    domain: [pallet]
    range: [shipment, warehouse]
    aliases: [上柜]
"""


class TestPackExtendsChain:
    """extends：社区包挂在某个域包之上，只写增量，约束可引用父包类型"""

    def test_extends_inherits_parent_vocabulary(self, registry):
        registry.import_pack(COMMUNITY_PACK_YAML)
        registry.import_pack(EXTENDS_PACK_YAML)

        links = {l.key for l in registry.link_types("warehouse_ops")}
        assert {"装载于", "存放于", "管理"} <= links        # 本包 + 父包 + 基底
        objects = {o.key for o in registry.object_types("warehouse_ops")}
        assert {"pallet", "shipment", "warehouse", "person"} <= objects
        assert registry.resolve_predicate_any("上柜") == "装载于"

    def test_constraints_may_reference_parent_types(self, registry):
        registry.import_pack(COMMUNITY_PACK_YAML)
        registry.import_pack(EXTENDS_PACK_YAML)

        ok, reason = registry.validate_predicate_types(
            "装载于", "pallet", "warehouse", domain="warehouse_ops")
        assert ok is True and reason == ""
        ok, reason = registry.validate_predicate_types(
            "装载于", "person", "warehouse", domain="warehouse_ops")
        assert ok is False and "定义域" in reason

    def test_extends_missing_parent_rejected(self, registry):
        with pytest.raises(OntologyError) as err:
            registry.import_pack(EXTENDS_PACK_YAML)

        assert "logistics" in str(err.value)
        assert "warehouse_ops" not in registry.domains()

    def test_rejected_extends_leaves_version_untouched(self, registry):
        registry.import_pack(COMMUNITY_PACK_YAML)
        before = registry.version

        with pytest.raises(OntologyError):
            registry.import_pack(EXTENDS_PACK_YAML.replace("range: [shipment, warehouse]",
                                                          "range: [ghost]"))

        assert registry.version == before
        assert "warehouse_ops" not in registry.domains()

    def test_extends_self_reference_rejected(self, registry):
        registry.import_pack(COMMUNITY_PACK_YAML)
        self_cycle = EXTENDS_PACK_YAML.replace("extends: logistics", "extends: warehouse_ops")

        with pytest.raises(OntologyError) as err:
            registry.import_pack(self_cycle)

        assert "环" in str(err.value)

    def test_extends_two_pack_cycle_rejected_on_load(self, tmp_path):
        packs = tmp_path / "packs"
        packs.mkdir()
        (packs / "general.yaml").write_text(BASE_PACK_YAML, encoding="utf-8")
        user = tmp_path / "user_packs"
        user.mkdir()
        (user / "c1.yaml").write_text(
            "name: c1\nextends: c2\nlink_types:\n  - key: 甲\n", encoding="utf-8")
        (user / "c2.yaml").write_text(
            "name: c2\nextends: c1\nlink_types:\n  - key: 乙\n", encoding="utf-8")

        reg = OntologyRegistry(packs_dir=str(packs), user_packs_dir=str(user))

        with pytest.raises(OntologyError) as err:
            reg.load()

        assert "环" in str(err.value)

    def test_export_roundtrip_keeps_extends(self, registry):
        registry.import_pack(COMMUNITY_PACK_YAML)
        registry.import_pack(EXTENDS_PACK_YAML)

        exported = registry.export_pack("warehouse_ops")

        assert yaml.safe_load(exported)["extends"] == "logistics"
        assert parse_pack(yaml.safe_load(exported)).extends == "logistics"

    def test_shipped_example_pack_extends_builtin_workforce(self, tmp_path):
        """examples/ontology/rd_efficiency.yaml 必须能挂进真实内置包"""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        text = open(os.path.join(repo_root, "examples", "ontology", "rd_efficiency.yaml"),
                    encoding="utf-8").read()
        reg = OntologyRegistry(packs_dir=PACKS_DIR, user_packs_dir=str(tmp_path))
        reg.load()

        reg.import_pack(text)

        links = {l.key for l in reg.link_types("rd_efficiency")}
        assert {"任职于", "管理"} <= links                 # 继承 workforce
        assert {"维护", "评审通过"} <= links               # 自己的增量
        objects = {o.key for o in reg.object_types("rd_efficiency")}
        assert {"employee", "system_component", "review"} <= objects


class TestVocabularyUsage:

    def test_fallback_ratio_and_unused_and_undeclared(self, monkeypatch):
        use_graph(monkeypatch, FakeGraph(predicate_usage={
            "管理": 10, "其他": 4, "野生谓词": 1}))

        result = governance.vocabulary_usage()

        assert result["total_edges"] == 15
        assert result["fallback_count"] == 4
        assert result["fallback_ratio"] == pytest.approx(0.2667, abs=1e-3)
        assert result["by_predicate"][0]["predicate"] == "管理"
        assert result["undeclared_predicates"] == ["野生谓词"]
        assert "管理" not in result["unused_link_types"]

    def test_empty_graph_is_not_division_error(self, monkeypatch):
        use_graph(monkeypatch, FakeGraph())
        result = governance.vocabulary_usage()

        assert result["total_edges"] == 0
        assert result["fallback_ratio"] == 0.0

    def test_alias_candidates_list_raw_variants(self, monkeypatch):
        use_graph(monkeypatch, FakeGraph(variants=[
            {"predicate": "管理", "raw_predicate": "负责", "count": 7}]))

        assert governance.alias_candidates(limit=5) == [
            {"predicate": "管理", "raw_predicate": "负责", "count": 7}]


class TestCompliance:

    def test_illegal_and_unused_object_types(self, monkeypatch):
        use_graph(monkeypatch, FakeGraph(type_usage={"person": 5, "机器人": 2}))
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(governance, "object_type_keys", lambda: ["person", "organization", "other"])
            result = governance.type_usage_report()

        assert result["total_entities"] == 7
        assert result["illegal_types"] == [{"type": "机器人", "count": 2}]
        assert "organization" in result["unused_types"]

    def test_domain_range_violation_detected(self, monkeypatch, registry):
        use_graph(monkeypatch, FakeGraph(pairs=[
            {"predicate": "管理", "subject_type": "organization",
             "object_type": "person", "count": 3},
            {"predicate": "管理", "subject_type": "person",
             "object_type": "organization", "count": 8}]))
        monkeypatch.setattr(governance, "ontology_registry", registry)

        violations = governance.domain_range_violations()

        assert len(violations) == 1
        assert violations[0]["subject_type"] == "organization"
        assert violations[0]["allowed_domain"] == ["person"]
        assert violations[0]["allowed_range"] == ["organization"]

    def test_unconstrained_link_type_never_violates(self, monkeypatch, registry):
        registry.import_pack("name: open\nlink_types:\n  - key: 关联\n")
        use_graph(monkeypatch, FakeGraph(pairs=[
            {"predicate": "关联", "subject_type": "person",
             "object_type": "organization", "count": 2}]))
        monkeypatch.setattr(governance, "ontology_registry", registry)

        assert governance.domain_range_violations() == []

    def test_unknown_predicate_pairs_are_skipped(self, monkeypatch, registry):
        use_graph(monkeypatch, FakeGraph(pairs=[
            {"predicate": "野生谓词", "subject_type": "person",
             "object_type": "person", "count": 1}]))
        monkeypatch.setattr(governance, "ontology_registry", registry)

        assert governance.domain_range_violations() == []


class TestReport:

    def test_findings_summarize_every_problem(self, monkeypatch, registry):
        use_graph(monkeypatch, FakeGraph(
            predicate_usage={"管理": 1, "其他": 9},
            type_usage={"person": 1, "机器人": 1},
            pairs=[{"predicate": "管理", "subject_type": "organization",
                    "object_type": "organization", "count": 1}],
            isolated=[{"entity_id": "e1", "name": "孤儿", "type": "person",
                       "datasource": "DOC://s1/a.md"}],
            gaps={"entities": 3, "relationships": 1}))
        monkeypatch.setattr(governance, "ontology_registry", registry)

        result = governance.report()

        assert result["domains"] == ["general"]
        assert any("兜底" in f for f in result["findings"])
        assert any("非法实体类型" in f for f in result["findings"])
        assert any("定义域" in f for f in result["findings"])
        assert any("游离实体" in f for f in result["findings"])
        assert any("无来源佐证" in f for f in result["findings"])

    def test_clean_graph_reports_no_issue(self, monkeypatch, registry):
        use_graph(monkeypatch, FakeGraph(predicate_usage={"管理": 4},
                                         type_usage={"person": 2}))
        monkeypatch.setattr(governance, "ontology_registry", registry)

        assert governance.report()["findings"] == ["图谱与本体一致，未发现治理项"]

    def test_domain_param_embeds_pack_yaml(self, monkeypatch, registry):
        use_graph(monkeypatch, FakeGraph())
        monkeypatch.setattr(governance, "ontology_registry", registry)

        assert governance.report(domain="general")["pack"].startswith("name: general")


class TestOntologyRoutes:

    @pytest.fixture()
    def client(self, registry, monkeypatch):
        from api.routes.ontology import router

        app = FastAPI()
        app.include_router(router, prefix="/api/ontology")
        monkeypatch.setattr("api.routes.ontology.ontology_registry", registry)
        use_graph(monkeypatch, FakeGraph(predicate_usage={"管理": 2}))
        return TestClient(app)

    def test_domains_lists_sizes(self, client):
        resp = client.get("/api/ontology/domains")

        assert resp.status_code == 200
        assert resp.json()["domains"] == [
            {"name": "general", "description": "基底包",
             "object_type_count": 3, "link_type_count": 2}]

    def test_export_pack(self, client):
        resp = client.get("/api/ontology/packs/general")

        assert resp.status_code == 200
        assert resp.json()["yaml"].startswith("name: general")
        assert client.get("/api/ontology/packs/不存在").status_code == 404

    def test_import_pack_and_rejection(self, client):
        ok = client.post("/api/ontology/packs", json={"yaml": COMMUNITY_PACK_YAML})
        assert ok.status_code == 200
        assert ok.json()["link_type_count"] == 1

        bad = client.post("/api/ontology/packs",
                          json={"yaml": COMMUNITY_PACK_YAML.replace(
                              "range: [warehouse]", "range: [ghost_type]")})
        assert bad.status_code == 400
        assert "ghost_type" in bad.json()["detail"]
        assert client.post("/api/ontology/packs", json={}).status_code == 400

    def test_reload_returns_domains(self, client):
        resp = client.post("/api/ontology/reload")

        assert resp.status_code == 200
        assert "general" in resp.json()["domains"]

    def test_report_endpoint(self, client):
        resp = client.get("/api/ontology/report", params={"limit": 10})

        assert resp.status_code == 200
        body = resp.json()
        assert body["vocabulary"]["total_edges"] == 2
        assert body["structure_issues"]["isolated_entities"] == []
        assert "pack" not in body

        assert client.get("/api/ontology/report",
                          params={"domain": "general", "with_pack": True}
                          ).json()["pack"].startswith("name: general")


def test_builtin_packs_stay_valid():
    """内置四个域包必须始终通过同一套校验（社区包的验收标准与内置包一致）"""
    reg = OntologyRegistry(packs_dir=PACKS_DIR, user_packs_dir=PACKS_DIR)
    reg.reload()

    assert reg.domains() == ["finance", "general", "medical", "workforce"]
    assert reg.export_pack("medical")
    assert reg.resolve_predicate_any("治疗")


class TestRegistryVersion:

    def test_version_bumps_on_register_and_reload(self, registry):
        before = registry.version

        registry.import_pack(COMMUNITY_PACK_YAML)
        assert registry.version == before + 1

        registry.reload()
        assert registry.version == before + 2

    def test_rejected_pack_leaves_version_untouched(self, registry):
        before = registry.version
        broken = COMMUNITY_PACK_YAML.replace("range: [warehouse]", "range: [ghost_type]")

        with pytest.raises(OntologyError):
            registry.import_pack(broken)

        assert registry.version == before


class TestPromptTracksVocabulary:
    """抽取 prompt 的词表片段必须跟随注册表版本，社区包导入后无需重启即进 prompt"""

    @pytest.fixture()
    def prompt_module(self, monkeypatch, registry):
        from ontology import prompt as module
        module.clear_cache()
        monkeypatch.setattr(module, "ontology_registry", registry)
        yield module
        module.clear_cache()

    def test_imported_pack_reaches_prompt_without_clearing_cache(self, prompt_module, registry):
        before = prompt_module.prompt_sections("logistics")
        assert "存放于" not in before["link_types"]

        registry.import_pack(COMMUNITY_PACK_YAML)
        after = prompt_module.prompt_sections("logistics")

        assert "- 存放于: 存放于（主语类型 shipment; 宾语类型 warehouse）" in after["link_types"]
        assert "- 管理: " in after["link_types"]

    def test_unchanged_registry_keeps_cached_render(self, prompt_module):
        assert prompt_module.prompt_sections("general") is \
               prompt_module.prompt_sections("general")
