"""数据库侧组件的纯函数行为

覆盖：
1. `entity_extraction.database.row_reader.safe_identifier` 标识符白名单（literal_column 无参数化能力，注入防护唯一缝）
2. `summary_generation.database.store` 概要 JSON 的目录/文件名约定（DBS/{conn}/{db}.json）
3. `content_extraction.database.dialects` 各方言都实现视图提取（D4 契约）
"""
import pytest

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
