"""
测试配置和共享 Fixtures

提供 Neo4j Mock、SQLite 临时库、LLM Mock 等测试基础设施。
"""
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# 确保 backend 在 sys.path 中
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_BACKEND_DIR))


# ============================================================
# 数据库 Fixtures
# ============================================================

@pytest.fixture
def temp_db():
    """创建临时 SQLite 数据库，测试结束后自动清理"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # 创建所有表
    from config.database import Base
    Base.metadata.create_all(bind=engine)

    yield SessionLocal

    # 清理
    engine.dispose()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def db_session(temp_db):
    """提供临时数据库会话"""
    db = temp_db()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# Neo4j Mock
# ============================================================

@pytest.fixture
def mock_neo4j():
    """Mock Neo4j 连接，返回预设的查询结果"""
    mock = MagicMock()
    mock.execute_query.return_value = []
    mock.initialize_schema.return_value = None

    with patch("config.neo4j_config.neo4j_conn", mock):
        yield mock


# ============================================================
# LLM Mock
# ============================================================

class MockModelClient:
    """模拟 LLM 调用，返回预设答案"""

    def __init__(self):
        self.call_count = 0
        self._responses: Dict[str, str] = {}
        self._default_response = "{}"

    def set_response(self, prompt_keyword: str, response: str):
        self._responses[prompt_keyword] = response

    def set_default_response(self, response: str):
        self._default_response = response

    def chat_completion(self, messages: List[Dict], **kwargs) -> str:
        self.call_count += 1
        prompt_text = str(messages)
        for keyword, response in self._responses.items():
            if keyword in prompt_text:
                return response
        return self._default_response

    def call_with_tools(self, messages: List[Dict], tools: List[Dict], **kwargs) -> Dict:
        self.call_count += 1
        return {"content": self._default_response, "tool_calls": []}


@pytest.fixture
def mock_model_client():
    """提供 Mock LLM 客户端"""
    client = MockModelClient()
    with patch("model_management.model_client.ModelClient", return_value=client):
        yield client


# ============================================================
# 测试数据 Fixtures
# ============================================================

@pytest.fixture
def sample_query() -> Dict[str, Any]:
    """示例查询分析结果"""
    return {
        "domain": "general",
        "intent": "分析实体关系",
        "entities": ["张三", "李四"],
        "entity_types": {"张三": "人员", "李四": "人员"},
        "constraints": {},
        "required_sources": ["graph"],
        "sub_questions": ["张三和李四有什么关联？"],
        "reasoning": "用户询问两人之间的关系",
        "direct_answer": "",
    }


@pytest.fixture
def sample_raw_evidence() -> List[Dict]:
    """示例原始证据"""
    from decision_engine.contracts import RawEvidence
    return [
        RawEvidence(
            source_type="entity",
            source_id="ent-001",
            content={"name": "张三", "type": "人员", "description": "工程师"},
            relevance_score=0.8,
            metadata={"name": "张三"},
        ),
        RawEvidence(
            source_type="graph_relation",
            source_id="rel-001",
            content={"source": "张三", "target": "李四", "predicate": "同事"},
            relevance_score=0.7,
            metadata={"source": "张三", "target": "李四"},
        ),
        RawEvidence(
            source_type="document_summary",
            source_id="doc-001",
            content={"summary": "张三和李四是同一团队的成员"},
            relevance_score=0.6,
            metadata={"doc_name": "团队介绍.md", "datasource": "DOC://local"},
        ),
    ]


@pytest.fixture
def sample_decision_request() -> Dict[str, Any]:
    """示例决策请求"""
    return {
        "question": "张三和李四是什么关系？",
        "domain": "general",
        "session_id": f"test-session-{uuid.uuid4().hex[:8]}",
        "context": {},
    }


# ============================================================
# CDC 测试 Fixtures
# ============================================================

@pytest.fixture
def sample_schema_cache():
    """示例 SchemaCache，用于 CDC 测试"""
    from cdc.schema_cache import SchemaCache

    cache = SchemaCache(
        connection_id="test-conn",
        database_name="test_db",
        connector_type="mysql",
    )

    # 手动填充测试数据
    cache.tables = ["users", "orders"]
    cache.table_columns = {
        "users": ["id", "name", "email"],
        "orders": ["id", "user_id", "amount"],
    }
    cache.pk_columns = {
        "users": ["id"],
        "orders": ["id"],
    }
    cache.fk_columns = {
        "orders": [{
            "column": "user_id",
            "referenced_table_name": "users",
            "referenced_column_name": "id",
        }],
    }
    cache.entity_types = {
        "users": "用户",
        "orders": "订单",
    }

    return cache


@pytest.fixture
def sample_debezium_event_insert() -> Dict[str, Any]:
    """示例 Debezium INSERT 事件"""
    return {
        "op": "c",
        "source": {"table": "users"},
        "after": {"id": 1, "name": "张三", "email": "zhangsan@example.com"},
    }


@pytest.fixture
def sample_debezium_event_update() -> Dict[str, Any]:
    """示例 Debezium UPDATE 事件"""
    return {
        "op": "u",
        "source": {"table": "users"},
        "after": {"id": 1, "name": "张三（更新）", "email": "zhangsan_new@example.com"},
        "before": {"id": 1, "name": "张三", "email": "zhangsan@example.com"},
    }


@pytest.fixture
def sample_debezium_event_delete() -> Dict[str, Any]:
    """示例 Debezium DELETE 事件"""
    return {
        "op": "d",
        "source": {"table": "users"},
        "before": {"id": 1, "name": "张三", "email": "zhangsan@example.com"},
    }


# ============================================================
# 记忆系统 Fixtures
# ============================================================

@pytest.fixture
def temp_memory_dir():
    """创建临时记忆目录"""
    tmpdir = tempfile.mkdtemp()
    memory_dir = os.path.join(tmpdir, "conversations")
    os.makedirs(memory_dir, exist_ok=True)
    memory_file = os.path.join(memory_dir, "MEMORY.md")

    yield memory_dir, memory_file

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# 辅助函数
# ============================================================

def make_short_term_memory(
    content: str,
    category: str = "fact",
    importance: float = 0.5,
    session_id: str = "test",
    domain: str = "general",
    days_ago: int = 0,
) -> "ShortTermMemory":
    """创建短期记忆 ORM 对象"""
    from models.memory import ShortTermMemory

    return ShortTermMemory(
        id=uuid.uuid4().hex[:12],
        content=content,
        category=category,
        importance=importance,
        session_id=session_id,
        domain=domain,
        created_at=datetime.now() - timedelta(days=days_ago),
        expires_at=datetime.now() + timedelta(days=7 - days_ago),
    )