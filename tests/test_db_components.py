"""数据库侧组件的纯函数行为

覆盖：
1. `entity_extraction.database.row_reader.safe_identifier` 标识符白名单（literal_column 无参数化能力，注入防护唯一缝）
2. `summary_generation.database.store` 概要 JSON 的目录/文件名约定（DBS/{conn}/{db}.json）
3. `content_extraction.database.dialects` 各方言都实现视图提取（D4 契约）
4. `content_extraction.database.store` Schema 产物按 (连接, 库) 隔离，同连接换库不互相覆盖
"""
import pytest

# 模块级导入：temp_db fixture 在会话创建时即 create_all，需先注册 Schema 产物表
import models.database  # noqa: F401
from models.database import AnalyzedTable
from summary_generation.database import store as db_summary_store
from entity_extraction.database.row_reader import safe_identifier


pytestmark = pytest.mark.unit


class TestSafeIdentifier:

    @pytest.mark.parametrize("name", ["users", "order_items", "_tmp", "T1", "a$b"])
    def test_accepts_plain_identifiers(self, name):
        assert safe_identifier(name) == name

    @pytest.mark.parametrize("name", [
        "users; DROP TABLE x",
        "users--",
        "1users",
        "user name",
        "",
        'a"b',
        "a`b",
    ])
    def test_rejects_injection_shapes(self, name):
        with pytest.raises(Exception):
            safe_identifier(name)


class TestDatabaseSummaryStore:

    def test_path_layout_is_dbs_scoped(self):
        path = db_summary_store.summary_path("conn_1", "shop")
        assert path.endswith("shop.json")
        assert path.startswith(db_summary_store.SUMMARY_ROOT)
        assert "DB" in db_summary_store.SUMMARY_ROOT
        assert db_summary_store.summary_path("conn_1", "shop").startswith(
            db_summary_store.summary_dir("conn_1"))

    def test_missing_db_name_falls_back_to_default_file(self):
        assert db_summary_store.summary_path("conn_1", None).endswith("database_summary.json")

    def test_save_then_load_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db_summary_store, "SUMMARY_ROOT", str(tmp_path))
        payload = {"db_name": "shop", "table_count": 3, "structure": []}
        path = db_summary_store.save("conn_1", "shop", payload)
        assert path.endswith("shop.json")
        assert db_summary_store.load("conn_1", "shop") == payload
        assert db_summary_store.has_data("conn_1") is True
        assert db_summary_store.has_data("nope") is False

    def test_load_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db_summary_store, "SUMMARY_ROOT", str(tmp_path))
        assert db_summary_store.load("conn_1", "absent") == {}


class TestDialectViewContract:

    def test_all_dialects_expose_extract_views(self):
        from content_extraction.database import dialects

        assert dialects.DIALECT_MAP, "方言注册表不应为空"
        for name, dialect_cls in dialects.DIALECT_MAP.items():
            assert callable(getattr(dialect_cls, "extract_views", None)), \
                f"方言 {name} 缺少 extract_views（D4：各方言都要提取视图）"


def _fake_schema(table_name, business_description):
    return {
        "tables": [{"TABLE_NAME": table_name, "TABLE_TYPE": "BASE TABLE",
                    "business_description": business_description}],
        "columns": [{"TABLE_NAME": table_name, "COLUMN_NAME": "id",
                     "DATA_TYPE": "int", "COLUMN_KEY": "PRI"}],
        "foreign_keys": [],
        "inferred_relationships": [{"source_table": table_name,
                                    "target_table": "other",
                                    "relationship_type": "contains"}],
    }


class TestSchemaStoreDatabaseIsolation:
    """同连接多库：后分析的库不得覆盖先分析的库（缺陷②回归）"""

    def test_second_database_does_not_overwrite_first(self, temp_db):
        from content_extraction.database.store import schema_store

        db = temp_db()
        try:
            assert schema_store.save_schema(db, "conn-1", "db_one",
                                            _fake_schema("t_order", "订单库订单表"))
            assert schema_store.save_schema(db, "conn-1", "db_two",
                                            _fake_schema("t_order", "结算库订单表"))

            one = schema_store.get_schema(db, "conn-1", "db_one")
            two = schema_store.get_schema(db, "conn-1", "db_two")
            assert [t["business_description"] for t in one["tables"]] == ["订单库订单表"]
            assert [t["business_description"] for t in two["tables"]] == ["结算库订单表"]
            assert len(one["columns"]) == 1 and len(two["columns"]) == 1
            assert len(one["inferred_relationships"]) == 1
        finally:
            db.close()

    def test_delete_schema_scoped_to_one_database(self, temp_db):
        from content_extraction.database.store import schema_store

        db = temp_db()
        try:
            schema_store.save_schema(db, "conn-1", "db_one", _fake_schema("t_a", "A"))
            schema_store.save_schema(db, "conn-1", "db_two", _fake_schema("t_b", "B"))
            schema_store.delete_schema(db, "conn-1", "db_one", "mysql")
            assert schema_store.get_schema(db, "conn-1", "db_one")["tables"] == []
            assert [t["table_name"] for t in
                    schema_store.get_schema(db, "conn-1", "db_two")["tables"]] == ["t_b"]
        finally:
            db.close()

    def test_analyzed_tables_uri_uses_own_database(self, temp_db):
        from content_extraction.database.store import schema_store

        db = temp_db()
        try:
            schema_store.save_analyzed_tables(db, "conn-1", "db_one",
                                              [{"table_name": "t_order"}])
            schema_store.save_analyzed_tables(db, "conn-1", "db_two",
                                              [{"table_name": "t_order"}])
            db.commit()
            rows = db.query(AnalyzedTable).filter(
                AnalyzedTable.connection_id == "conn-1").all()
            assert {r.uri for r in rows} == {
                "DBS://conn-1/db_one/t_order", "DBS://conn-1/db_two/t_order"}
            # 同库重跑不产生重复行
            schema_store.save_analyzed_tables(db, "conn-1", "db_two",
                                              [{"table_name": "t_order"}])
            db.commit()
            assert db.query(AnalyzedTable).filter(
                AnalyzedTable.connection_id == "conn-1").count() == 2
        finally:
            db.close()

    def test_sqlite_db_name_normalizes_to_basename(self):
        from content_extraction.database.store import normalize_db_name

        assert normalize_db_name("D:\\data\\shop.db", "sqlite") == "shop.db"
        assert normalize_db_name(None, "sqlite") == "default"
        assert normalize_db_name("shop", "mysql") == "shop"

    def test_duplicate_inferred_relationships_do_not_break_save(self, temp_db):
        """LLM 可给出同一对表的重复推断，落库必须去重而非撞主键后整体失败"""
        from content_extraction.database.store import schema_store

        schema = _fake_schema("t_order", "订单表")
        rel = schema["inferred_relationships"][0]
        schema["inferred_relationships"] = [dict(rel), dict(rel)]

        db = temp_db()
        try:
            schema_store.save_schema(db, "conn-1", "db_one", schema)
            saved = schema_store.get_schema(db, "conn-1", "db_one")
            assert len(saved["inferred_relationships"]) == 1
        finally:
            db.close()

    def test_analyzed_tables_are_committed(self, temp_db):
        """save_analyzed_tables 必须自提交，否则 handler 关闭会话后记录丢失"""
        from content_extraction.database.store import schema_store

        db = temp_db()
        try:
            schema_store.save_analyzed_tables(db, "conn-1", "db_one",
                                              [{"table_name": "t_order"}])
        finally:
            db.close()

        db2 = temp_db()
        try:
            rows = db2.query(AnalyzedTable).filter(
                AnalyzedTable.connection_id == "conn-1").all()
            assert [r.uri for r in rows] == ["DBS://conn-1/db_one/t_order"]
        finally:
            db2.close()


class TestDatabaseTaskPayloadCarriesDatabaseName:
    """任务的数据源显示只认创建时锁定的库名（缺陷①回归）"""

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

    def test_analyze_locks_database_name_into_payload(self, client):
        c, captured = client
        assert c.post("/api/database/conn-1/analyze",
                      json={"database": "employees"}).status_code == 200
        assert captured["payload"]["database_name"] == "employees"

    def test_import_locks_database_name_into_payload(self, client):
        c, captured = client
        assert c.post("/api/database/conn-1/import?database_name=sakila").status_code == 200
        assert captured["task_type"] == "database_schema_import"
        assert captured["payload"]["database_name"] == "sakila"

    def test_label_and_uri_use_payload_not_connection_selection(self):
        from task_management.task_manager import (
            _datasource_label_from_payload, _datasource_uri_from_payload)

        payload = {"connection_id": "conn-1", "database_name": "employees"}
        conn_aliases = {"conn-1": {"name": "本机MySQL", "database": "sakila"}}
        assert _datasource_label_from_payload(payload, conn_aliases) == "employees（本机MySQL）"
        assert _datasource_uri_from_payload(payload) == "DBS://conn-1/employees"
