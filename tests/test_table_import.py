"""④ 表格导入（纯规则列实体）—— 语义行装配与指纹闸门

Neo4j 打桩：只断言交给落库缝的实体/关系语义行，不验证写图（写图用例见 integration）。
"""
import hashlib
import json
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

from content_extraction.document.models import KIND_TABLE
from entity_extraction.document import extractor as extractor_mod
from entity_extraction.document import table_service
from entity_extraction.document.service import (
    DocumentExtractionService,
    guard_llm_available,
)
from knowledge_graph.entity_data_store import EntityDataStore

DOC = "DOC://s1/销售统计.csv"


def write_csv(tmp_path, header, rows, name="销售统计.csv"):
    text = "\r\n".join([",".join(header)] + [",".join(row) for row in rows]) + "\r\n"
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


def digest(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def column(name, role, type_=None, primary=False):
    item = {"n": name, "r": role, "d": f"{name}的业务解释", "primary": primary}
    if role == "entity":
        item["t"] = type_ or "other"
    return item


def leaf(title, columns, rels=None):
    return {"title": title, "kind": KIND_TABLE, "summary": "摘要", "text": "表档案",
            "table_columns": columns,
            "table_meta": {"row_count": 4, "col_count": len(columns),
                           "rels": rels or [], "skipped_reason": None}}


def make_summary(path, leaves, fmt="csv"):
    return {"doc_name": path.name, "format": fmt, "kind": KIND_TABLE, "page_count": None,
            "content_hash": digest(path),
            "structure": [{"title": path.name, "kind": KIND_TABLE, "summary": "", "text": "",
                           "nodes": leaves}]}


@pytest.fixture
def importer(monkeypatch):
    """落库替身：记录交给 save_all 的语义行；源路径解析直接指向 tmp 文件"""
    box = {"path": "", "calls": []}

    def fake_save_all(entities, relationships=None, datasource=None,
                      use_create=False, evidence_hash=None):
        box["calls"].append({"entities": entities,
                             "relationships": relationships or [],
                             "datasource": datasource, "evidence_hash": evidence_hash})
        return len(entities), len(relationships or [])

    monkeypatch.setattr(EntityDataStore, "save_all", staticmethod(fake_save_all))
    monkeypatch.setattr(table_service, "resolve_source_file",
                        lambda datasource: box["path"])
    return box


def entity_map(saved):
    return {item["n"]: item for item in saved["entities"]}


SALES_HEADER = ["部门", "省份", "销售额"]
SALES_ROWS = [["华东大区", "浙江", "120"], ["华北大区", "北京", "98"],
              ["华东大区", "浙江", "50"], ["合计", "", "300"]]


def sales_columns(primary=True):
    return [column("部门", "entity", "organization", primary=primary),
            column("省份", "entity", "location"),
            column("销售额", "attribute")]


SALES_RELS = [{"s": "部门", "p": "属于", "o": "省份"}]


class TestColumnEntities:
    def test_entities_types_attributes_and_rels(self, tmp_path, importer):
        path = write_csv(tmp_path, SALES_HEADER, SALES_ROWS)
        importer["path"] = str(path)
        result = table_service.import_tables(
            make_summary(path, [leaf("月度汇总", sales_columns(), SALES_RELS)]),
            DOC, evidence_hash=digest(path))

        assert result["entity_count"] == 4
        saved = importer["calls"][0]
        assert saved["datasource"] == DOC
        assert saved["evidence_hash"] == digest(path)

        entities = entity_map(saved)
        assert set(entities) == {"华东大区", "华北大区", "北京", "浙江"}
        assert entities["华东大区"]["t"] == "organization"
        assert entities["华东大区"]["c"] == 2
        assert entities["华东大区"]["d"] == "来自 销售统计.csv/月度汇总.部门"
        assert entities["华东大区"]["a"] == {"销售额": "120"}
        assert entities["浙江"]["t"] == "location"
        assert entities["浙江"]["c"] == 2
        assert entities["浙江"]["a"] == {}
        assert saved["relationships"] == [
            {"s": "华东大区", "p": "属于", "o": "浙江"},
            {"s": "华北大区", "p": "属于", "o": "北京"}]

        report = result["table_report"]
        assert report["sheets"] == ["月度汇总"]
        assert report["rows_read"] == 4
        # 「合计」是停用词行：主列为空 → 该行属性整行丢弃计数
        assert report["values_filtered"]["stopword"] == 1
        assert report["attribute_dropped_no_primary"] == 1

    def test_same_value_across_sheets_merges_into_one_entity(self, tmp_path, importer):
        rows = [["华东大区", "浙江", "120"], ["华北大区", "北京", "98"]]
        path = write_csv(tmp_path, SALES_HEADER, rows)
        importer["path"] = str(path)
        leaves = [leaf("月度汇总", sales_columns(), SALES_RELS),
                  leaf("季度汇总", sales_columns(), SALES_RELS)]
        result = table_service.import_tables(make_summary(path, leaves), DOC)

        saved = importer["calls"][0]
        assert result["entity_count"] == 4
        assert set(entity_map(saved)) == {"华东大区", "华北大区", "北京", "浙江"}
        assert saved["relationships"] == [
            {"s": "华东大区", "p": "属于", "o": "浙江"},
            {"s": "华北大区", "p": "属于", "o": "北京"}]


class TestPrimaryAndAttributes:
    def test_no_primary_designated_drops_all_attributes(self, tmp_path, importer):
        path = write_csv(tmp_path, SALES_HEADER, SALES_ROWS)
        importer["path"] = str(path)
        table_service.import_tables(
            make_summary(path, [leaf("月度汇总",
                                     sales_columns(primary=False), SALES_RELS)]), DOC)

        entities = entity_map(importer["calls"][0])
        assert entities["华东大区"]["a"] == {}
        assert entities["华北大区"]["a"] == {}

    def test_empty_primary_cell_does_not_fill_from_previous_row(self, tmp_path, importer):
        rows = [["华东大区", "浙江", "120"], ["", "江苏", "70"]]
        path = write_csv(tmp_path, SALES_HEADER, rows)
        importer["path"] = str(path)
        result = table_service.import_tables(
            make_summary(path, [leaf("月度汇总", sales_columns(), SALES_RELS)]), DOC)

        entities = entity_map(importer["calls"][0])
        assert entities["华东大区"]["a"] == {"销售额": "120"}
        assert entities["江苏"]["a"] == {}
        assert result["table_report"]["attribute_dropped_no_primary"] == 1

    def test_sheet_without_entity_column_imports_nothing(self, tmp_path, importer):
        path = write_csv(tmp_path, SALES_HEADER, SALES_ROWS)
        importer["path"] = str(path)
        columns = [column("部门", "none"), column("省份", "none"),
                   column("销售额", "attribute")]
        result = table_service.import_tables(make_summary(path, [leaf("月度汇总", columns)]),
                                            DOC)

        assert result["entity_count"] == 0
        assert importer["calls"] == []
        guard_llm_available(result, "导入")  # 合法 0 实体不该让任务失败


class TestLimits:
    def test_high_cardinality_column_downgrades_to_attribute(self, tmp_path, importer,
                                                             monkeypatch):
        monkeypatch.setattr(table_service, "COLUMN_ENTITY_LIMIT", 2)
        header = ["部门", "订单号", "金额"]
        rows = [["华东大区", "A1", "10"], ["华东大区", "A2", "20"],
                ["华北大区", "A3", "30"]]
        path = write_csv(tmp_path, header, rows)
        importer["path"] = str(path)
        columns = [column("部门", "entity", "organization", primary=True),
                   column("订单号", "entity", "concept"),
                   column("金额", "attribute")]
        rels = [{"s": "部门", "p": "关联", "o": "订单号"}]
        result = table_service.import_tables(
            make_summary(path, [leaf("明细", columns, rels)]), DOC)

        saved = importer["calls"][0]
        assert set(entity_map(saved)) == {"华东大区", "华北大区"}
        assert entity_map(saved)["华东大区"]["a"] == {"订单号": "A1", "金额": "10"}
        report = result["table_report"]
        assert report["column_downgraded_high_cardinality"] == ["明细.订单号"]
        assert report["rel_endpoint_dropped"] == 3
        assert saved["relationships"] == []

    def test_sheet_entity_limit_keeps_primary_column_only(self, tmp_path, importer,
                                                         monkeypatch):
        monkeypatch.setattr(table_service, "SHEET_ENTITY_LIMIT", 3)
        path = write_csv(tmp_path, SALES_HEADER, SALES_ROWS[:2])
        importer["path"] = str(path)
        result = table_service.import_tables(
            make_summary(path, [leaf("月度汇总", sales_columns(), SALES_RELS)]), DOC)

        saved = importer["calls"][0]
        assert set(entity_map(saved)) == {"华东大区", "华北大区"}
        # 没建成实体的列值退回属性，不丢信息
        assert entity_map(saved)["华东大区"]["a"] == {"销售额": "120", "省份": "浙江"}
        assert result["table_report"]["sheet_entity_limit_hit"] == ["月度汇总"]
        assert saved["relationships"] == []

    def test_row_cap_applies_to_import(self, tmp_path, importer, monkeypatch):
        monkeypatch.setattr(table_service, "MAX_ROWS_READ", 2)
        path = write_csv(tmp_path, SALES_HEADER, SALES_ROWS)
        importer["path"] = str(path)
        result = table_service.import_tables(
            make_summary(path, [leaf("月度汇总", sales_columns(), SALES_RELS)]), DOC)

        assert result["table_report"]["rows_read"] == 2


class TestValueFilters:
    def test_short_numeric_and_stopword_values_never_become_entities(self, tmp_path,
                                                                     importer):
        header = ["代号", "数量", "部门"]
        rows = [["A", "12", "华东大区"], ["", "", "小计"], ["浙", "3.5", "N/A"],
                ["B2", "7", "合计"]]
        path = write_csv(tmp_path, header, rows)
        importer["path"] = str(path)
        columns = [column("代号", "entity", "concept"),
                   column("数量", "entity", "other"),
                   column("部门", "entity", "organization", primary=True)]
        table_service.import_tables(make_summary(path, [leaf("表", columns)]), DOC)

        assert set(entity_map(importer["calls"][0])) == {"B2", "华东大区"}


class TestOntologyValidation:
    def test_out_of_vocabulary_type_falls_back_to_other(self, tmp_path, importer):
        path = write_csv(tmp_path, ["城市", "级别"], [["杭州", "一线"]])
        importer["path"] = str(path)
        columns = [column("城市", "entity", "region", primary=True),
                   column("级别", "none")]
        table_service.import_tables(make_summary(path, [leaf("表", columns)]), DOC)

        entity = entity_map(importer["calls"][0])["杭州"]
        assert entity["t"] == "other"
        assert entity["a"]["raw_type"] == "region"

    def test_in_vocabulary_type_kept(self, tmp_path, importer):
        path = write_csv(tmp_path, ["城市", "级别"], [["杭州", "一线"]])
        importer["path"] = str(path)
        columns = [column("城市", "entity", "location", primary=True),
                   column("级别", "none")]
        table_service.import_tables(make_summary(path, [leaf("表", columns)]), DOC)

        entity = entity_map(importer["calls"][0])["杭州"]
        assert entity["t"] == "location"
        assert "raw_type" not in entity["a"]

    def test_column_named_raw_type_yields_to_the_marker(self, tmp_path, importer):
        """真列名与治理标记共用 attributes 这一个命名空间时，列值让位且必须留痕"""
        path = write_csv(tmp_path, ["城市", "raw_type"], [["杭州", "一线"], ["宁波", "二线"]])
        importer["path"] = str(path)
        columns = [column("城市", "entity", "region", primary=True),
                   column("raw_type", "attribute")]
        result = table_service.import_tables(make_summary(path, [leaf("表", columns)]), DOC)

        assert entity_map(importer["calls"][0])["杭州"]["a"]["raw_type"] == "region"
        assert result["table_report"]["attribute_key_reserved"] == ["表.raw_type"]

    def test_in_vocabulary_column_named_raw_type_keeps_its_value(self, tmp_path, importer):
        """没有降级要记时不报警：这一列的取值就是普通属性，报告里不该出现它"""
        path = write_csv(tmp_path, ["城市", "raw_type"], [["杭州", "一线"]])
        importer["path"] = str(path)
        columns = [column("城市", "entity", "location", primary=True),
                   column("raw_type", "attribute")]
        result = table_service.import_tables(make_summary(path, [leaf("表", columns)]), DOC)

        assert entity_map(importer["calls"][0])["杭州"]["a"]["raw_type"] == "一线"
        assert result["table_report"]["attribute_key_reserved"] == []


class TestFingerprintGate:
    def test_mismatch_aborts_before_save(self, tmp_path, importer):
        path = write_csv(tmp_path, SALES_HEADER, SALES_ROWS)
        importer["path"] = str(path)
        summary = make_summary(path, [leaf("月度汇总", sales_columns(), SALES_RELS)])
        summary["content_hash"] = "0" * 32

        with pytest.raises(ValueError, match="源文件指纹与摘要不一致"):
            table_service.import_tables(summary, DOC)
        assert importer["calls"] == []

    def test_summary_without_hash_aborts(self, tmp_path, importer):
        path = write_csv(tmp_path, SALES_HEADER, SALES_ROWS)
        importer["path"] = str(path)
        summary = make_summary(path, [leaf("月度汇总", sales_columns())])
        summary.pop("content_hash")

        with pytest.raises(ValueError, match="源文件指纹与摘要不一致"):
            table_service.import_tables(summary, DOC)
        assert importer["calls"] == []

    def test_missing_source_file_aborts(self, tmp_path, importer):
        path = write_csv(tmp_path, SALES_HEADER, SALES_ROWS)
        importer["path"] = str(tmp_path / "已被删掉的.csv")

        with pytest.raises(FileNotFoundError):
            table_service.import_tables(make_summary(path, [leaf("月度汇总",
                                                                sales_columns())]), DOC)
        assert importer["calls"] == []


class TestRouting:
    def test_unannotated_table_summary_skips_import(self, tmp_path, importer):
        path = write_csv(tmp_path, SALES_HEADER, SALES_ROWS)
        importer["path"] = str(path)
        summary = make_summary(path, [leaf("月度汇总", [])])

        result = table_service.import_tables(summary, DOC)
        assert result["table_import_skipped"] == "无列标注"
        assert result["entity_count"] == 0
        assert result["batch_total"] == 0
        assert importer["calls"] == []
        guard_llm_available(result, "导入")

    def test_extract_from_summary_routes_by_table_kind(self, tmp_path, importer,
                                                     monkeypatch):
        path = write_csv(tmp_path, SALES_HEADER, SALES_ROWS)
        importer["path"] = str(path)
        summary = make_summary(path, [leaf("月度汇总", sales_columns(), SALES_RELS)])
        summary_path = tmp_path / "summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")

        calls = []
        monkeypatch.setattr(table_service, "import_tables",
                            lambda *args, **kwargs: calls.append((args, kwargs)) or
                            {"entity_count": 0, "relationship_count": 0,
                             "batch_total": 0, "batch_failed": 0})

        def no_enhancer(model_config=None):
            raise AssertionError("表格摘要不该构造 LLM 抽取器")

        monkeypatch.setattr(extractor_mod, "LLMEntityEnhancer", no_enhancer)

        result = DocumentExtractionService({"name": "不该被用到"}).extract_from_summary(
            str(summary_path), DOC, domain="sales", evidence_hash=summary["content_hash"])

        assert len(calls) == 1
        assert calls[0][0][1] == DOC
        assert calls[0][1]["domain"] == "sales"
        assert calls[0][1]["evidence_hash"] == summary["content_hash"]
        assert result["batch_failed"] == 0

    def test_prose_summary_stays_on_llm_branch(self, tmp_path, importer, monkeypatch):
        summary_path = tmp_path / "prose.json"
        summary_path.write_text(json.dumps({
            "doc_name": "说明.md", "format": "md", "content_hash": "x",
            "structure": [{"title": "章节", "summary": "", "text": "正文。" * 250}]},
            ensure_ascii=False), encoding="utf-8")

        imported = []
        monkeypatch.setattr(table_service, "import_tables",
                            lambda *a, **k: imported.append(a))
        instance = MagicMock()
        instance.extract_entities_and_relationships.return_value = {
            "entities": [], "relationships": [], "batch_failed": False}
        monkeypatch.setattr(extractor_mod, "LLMEntityEnhancer",
                            lambda model_config=None: instance)

        result = DocumentExtractionService({"name": "fake"}).extract_from_summary(
            str(summary_path), "DOC://s1/说明.md")

        assert imported == []
        assert result["batch_total"] == 1
        assert instance.extract_entities_and_relationships.call_count == 1

    def test_summary_without_kind_declaration_is_not_table_branch(self, tmp_path,
                                                                  monkeypatch):
        """分派依据是 ③ 落盘的 kind 声明，不再按扩展名反推

        没有该声明的摘要（改造前生成的旧文件）即使 format 是 csv 也走正文分支，
        必须重跑一轮摘要才会回到表格装配。
        """
        path = write_csv(tmp_path, SALES_HEADER, SALES_ROWS)
        summary = make_summary(path, [leaf("月度汇总", sales_columns())])
        summary.pop("kind")
        for parent in summary["structure"]:
            parent.pop("kind", None)
            for node in parent["nodes"]:
                node.pop("kind", None)
        summary_path = tmp_path / "stale.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")

        imported = []
        monkeypatch.setattr(table_service, "import_tables",
                            lambda *a, **k: imported.append(a))
        instance = MagicMock()
        instance.extract_entities_and_relationships.return_value = {
            "entities": [], "relationships": [], "batch_failed": False}
        monkeypatch.setattr(extractor_mod, "LLMEntityEnhancer",
                            lambda model_config=None: instance)

        DocumentExtractionService({"name": "fake"}).extract_from_summary(
            str(summary_path), DOC)

        assert imported == []


class TestXlsxSource:
    def test_two_sheets_read_by_title(self, tmp_path, importer):
        from openpyxl import Workbook

        path = tmp_path / "销售统计.xlsx"
        workbook = Workbook()
        first = workbook.active
        first.title = "月度汇总"
        first.append(SALES_HEADER)
        for row in SALES_ROWS[:2]:
            first.append(row)
        second = workbook.create_sheet("区域")
        second.append(["省份", "大区"])
        second.append(["浙江", "华东大区"])
        second.append(["北京", "华北大区"])
        workbook.save(path)
        importer["path"] = str(path)

        columns2 = [column("省份", "entity", "location", primary=True),
                    column("大区", "entity", "organization")]
        leaves = [leaf("月度汇总", sales_columns(), SALES_RELS),
                  leaf("区域", columns2, [{"s": "省份", "p": "属于", "o": "大区"}])]
        result = table_service.import_tables(
            make_summary(path, leaves, fmt="xlsx"), "DOC://s1/销售统计.xlsx")

        saved = importer["calls"][0]
        assert set(entity_map(saved)) == {"华东大区", "华北大区", "北京", "浙江"}
        assert ("华东大区", "属于", "浙江") in [(r["s"], r["p"], r["o"])
                                        for r in saved["relationships"]]
        assert result["table_report"]["rows_read"] == 4
