"""
CDC 事件处理器（event_processor.py）单元测试

测试 Debezium 事件 → Neo4j 操作映射（INSERT/UPDATE/DELETE）。
使用 Mock Neo4j，不依赖真实 Neo4j 服务。
"""
import hashlib
from unittest.mock import MagicMock, patch

import pytest

from cdc.event_processor import EventProcessor


@pytest.fixture
def mock_neo4j_conn():
    """Mock Neo4j 连接 — 同时 patch event_processor 模块中的引用"""
    mock = MagicMock()
    mock.execute_query.return_value = []

    with patch("cdc.event_processor.neo4j_conn", mock):
        yield mock


class TestEventProcessor:
    """EventProcessor 单元测试"""

    def test_process_insert_event(self, mock_neo4j_conn, sample_schema_cache, sample_debezium_event_insert):
        """处理 INSERT 事件：返回 'upsert'"""
        processor = EventProcessor(
            schema=sample_schema_cache,
            connection_id="test-conn",
            database_name="test_db",
        )

        result = processor.process_event(sample_debezium_event_insert)
        assert result == "upsert", f"INSERT 应返回 'upsert'，实际 {result}"
        assert mock_neo4j_conn.execute_query.call_count >= 1, "应调用 Neo4j 执行查询"

    def test_process_update_event(self, mock_neo4j_conn, sample_schema_cache, sample_debezium_event_update):
        """处理 UPDATE 事件：返回 'upsert'"""
        processor = EventProcessor(
            schema=sample_schema_cache,
            connection_id="test-conn",
            database_name="test_db",
        )

        result = processor.process_event(sample_debezium_event_update)
        assert result == "upsert", f"UPDATE 应返回 'upsert'，实际 {result}"
        assert mock_neo4j_conn.execute_query.call_count >= 1

    def test_process_delete_event(self, mock_neo4j_conn, sample_schema_cache, sample_debezium_event_delete):
        """处理 DELETE 事件：返回 'delete'"""
        processor = EventProcessor(
            schema=sample_schema_cache,
            connection_id="test-conn",
            database_name="test_db",
        )

        result = processor.process_event(sample_debezium_event_delete)
        assert result == "delete", f"DELETE 应返回 'delete'，实际 {result}"
        assert mock_neo4j_conn.execute_query.call_count >= 1, "应调用 DELETE 查询"

    def test_process_skip_unknown_op(self, mock_neo4j_conn, sample_schema_cache):
        """未知操作类型返回 'skip'"""
        processor = EventProcessor(
            schema=sample_schema_cache,
            connection_id="test-conn",
            database_name="test_db",
        )

        result = processor.process_event({"op": "x", "source": {"table": "users"}, "after": {}})
        assert result == "skip", "未知操作类型应返回 'skip'"

    def test_process_skip_empty_after(self, mock_neo4j_conn, sample_schema_cache):
        """INSERT 无 after 数据时返回 'skip'"""
        processor = EventProcessor(
            schema=sample_schema_cache,
            connection_id="test-conn",
            database_name="test_db",
        )

        result = processor.process_event({
            "op": "c",
            "source": {"table": "users"},
            "after": None,
        })
        assert result == "skip"

    def test_entity_id_consistency(self, mock_neo4j_conn, sample_schema_cache):
        """entity_id 与全量导入一致：MD5(name_type)"""
        processor = EventProcessor(
            schema=sample_schema_cache,
            connection_id="test-conn",
            database_name="test_db",
        )

        row = {"id": 42, "name": "测试用户"}
        entity_name = sample_schema_cache.build_entity_name("users", row)
        expected_id = hashlib.md5(entity_name.encode()).hexdigest()

        processor.process_event({
            "op": "c",
            "source": {"table": "users"},
            "after": row,
        })

        call_args = mock_neo4j_conn.execute_query.call_args_list[0]
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params["entity_id"] == expected_id, \
            f"entity_id 应与全量导入一致，期望 {expected_id}，实际 {params.get('entity_id', 'missing')}"

    def test_entity_name_format(self, mock_neo4j_conn, sample_schema_cache):
        """实体名称格式：{table}:{pk_value}"""
        row = {"id": 100, "name": "测试"}
        entity_name = sample_schema_cache.build_entity_name("users", row)
        assert entity_name == "users:100", f"实体名称应为 'users:100'，实际 {entity_name}"

    def test_entity_name_empty_pk(self, sample_schema_cache):
        """PK 值为空时返回空字符串"""
        row = {"id": None, "name": "测试"}
        entity_name = sample_schema_cache.build_entity_name("users", row)
        assert entity_name == "", "PK 为 None 应返回空字符串"

    def test_build_description(self, mock_neo4j_conn, sample_schema_cache):
        """描述生成：所有列 col=val 拼接"""
        processor = EventProcessor(
            schema=sample_schema_cache,
            connection_id="test-conn",
            database_name="test_db",
        )

        row = {"id": 1, "name": "张三", "email": "zhangsan@test.com"}
        desc = processor._build_description("users", row)
        assert "id=1" in desc
        assert "name=张三" in desc
        assert "email=zhangsan@test.com" in desc

    def test_build_description_no_columns(self, mock_neo4j_conn, sample_schema_cache):
        """无列缓存时回退到 row 遍历"""
        processor = EventProcessor(
            schema=sample_schema_cache,
            connection_id="test-conn",
            database_name="test_db",
        )

        sample_schema_cache.table_columns = {}
        row = {"key1": "val1", "key2": "val2"}
        desc = processor._build_description("unknown_table", row)
        assert "key1=val1" in desc
        assert "key2=val2" in desc

    def test_fk_relationship_upsert(self, mock_neo4j_conn, sample_schema_cache):
        """FK 关系同步：orders 表的 user_id 外键"""
        processor = EventProcessor(
            schema=sample_schema_cache,
            connection_id="test-conn",
            database_name="test_db",
        )

        mock_neo4j_conn.execute_query.return_value = []

        processor.process_event({
            "op": "c",
            "source": {"table": "orders"},
            "after": {"id": 1, "user_id": 42, "amount": 100.0},
        })

        total_calls = mock_neo4j_conn.execute_query.call_count
        assert total_calls >= 2, f"应有至少 2 次 Neo4j 调用（MERGE实体 + FK关系），实际 {total_calls}"

    def test_fk_relationship_update(self, mock_neo4j_conn, sample_schema_cache):
        """FK 值变更时：删除旧关系 + 创建新关系"""
        processor = EventProcessor(
            schema=sample_schema_cache,
            connection_id="test-conn",
            database_name="test_db",
        )

        mock_neo4j_conn.execute_query.side_effect = [
            [],  # MERGE 实体
            # 查询现有 FK 关系
            [{
                "rel_id": hashlib.md5(
                    f"orders:1_Foreign key_users:42".encode()
                ).hexdigest(),
                "target_name": "users:42",
            }],
            [],  # 删除旧关系
            [],  # 创建新关系
        ]

        processor.process_event({
            "op": "u",
            "source": {"table": "orders"},
            "after": {"id": 1, "user_id": 99, "amount": 200.0},
        })

        assert mock_neo4j_conn.execute_query.call_count >= 3, \
            f"应有至少 3 次调用，实际 {mock_neo4j_conn.execute_query.call_count}"


class TestSchemaCache:
    """SchemaCache 单元测试"""

    def test_build_entity_name_single_pk(self, sample_schema_cache):
        """单列主键：{table}:{pk_value}"""
        name = sample_schema_cache.build_entity_name("users", {"id": 42})
        assert name == "users:42"

    def test_build_entity_name_composite_pk(self, sample_schema_cache):
        """复合主键：{table}:{pk1}:{pk2}"""
        sample_schema_cache.pk_columns["users"] = ["id", "tenant_id"]
        name = sample_schema_cache.build_entity_name("users", {"id": 1, "tenant_id": 100})
        assert name == "users:1:100"

    def test_build_entity_name_empty_pk_value(self, sample_schema_cache):
        """PK 值为 None 时返回空"""
        name = sample_schema_cache.build_entity_name("users", {"id": None})
        assert name == ""

    def test_get_stream_keys_mysql(self, sample_schema_cache):
        """MySQL stream key 格式：{prefix}.{db}.{table}"""
        keys = sample_schema_cache.get_stream_keys("openpalantir")
        assert len(keys) == 2
        assert "openpalantir.test_db.users" in keys
        assert "openpalantir.test_db.orders" in keys

    def test_get_stream_keys_postgresql(self, sample_schema_cache):
        """PG stream key 格式：{prefix}.{schema}.{table}"""
        sample_schema_cache.connector_type = "postgresql"
        keys = sample_schema_cache.get_stream_keys("openpalantir")
        assert "openpalantir.public.users" in keys
        assert "openpalantir.public.orders" in keys

    def test_get_all_column_names(self, sample_schema_cache):
        """获取表的所有列名"""
        cols = sample_schema_cache.get_all_column_names("users")
        assert "id" in cols
        assert "name" in cols
        assert "email" in cols